"""
Simplified Account resolver service using TF-IDF only.

This implementation intentionally removes any LLM or embedding fallbacks
and relies solely on the TF-IDF filter provided by
`chatbot.agents.filters.account_resolver_filter.AccountResolverFilter`.

Public API kept compatible with the previous service so other code can
still pass an `aoai_client` argument to the constructor (it will be ignored).
"""

import structlog
from typing import Any, Dict, List, Optional

from chatbot.agents.filters.account_resolver_filter import AccountResolverFilter
from chatbot.models.account import Account
from chatbot.models.rbac import RBACContext
from chatbot.services.unified_service import UnifiedDataService

logger = structlog.get_logger(__name__)


class AccountResolverService:
    """TF-IDF-only account resolver.

    Constructor keeps the `aoai_client` parameter for backward compatibility
    but does not use it. The resolver will only use TF-IDF matching.
    """

    def __init__(
        self,
        aoai_client: Any,
        unified_data_service: UnifiedDataService,
        confidence_threshold: float = 0.8,
        max_suggestions: int = 3,
        tfidf_threshold: float = 0.3,
        use_tfidf: bool = True,
    ):
        # Keep aoai_client for compatibility; not used.
        self.aoai_client = aoai_client
        self.unified_data_service = unified_data_service
        self.confidence_threshold = confidence_threshold
        self.max_suggestions = max_suggestions
        self.use_tfidf = use_tfidf

        self.tfidf_filter: Optional[AccountResolverFilter] = None
        if self.use_tfidf:
            self.tfidf_filter = AccountResolverFilter(
                min_similarity=tfidf_threshold,
                max_candidates=max_suggestions * 2,
            )

        logger.info(
            "Account resolver (TF-IDF only) initialized",
            use_tfidf=self.use_tfidf,
            confidence_threshold=self.confidence_threshold,
            tfidf_threshold=tfidf_threshold,
        )

    async def resolve_account(
        self,
        user_query: str,
        rbac_context: RBACContext,
        allowed_accounts: Optional[List[Account]] = None,
    ) -> Dict[str, Any]:
        """Resolve account names using TF-IDF only.

        Returns a dictionary with keys similar to the previous implementation so
        callers remain compatible.
        """
        try:
            logger.info("Starting account resolution (TF-IDF)", user_id=rbac_context.user_id)

            if allowed_accounts is None:
                allowed_accounts = await self._get_allowed_accounts(rbac_context)

            if not allowed_accounts:
                logger.warning("No allowed accounts found for user", user_id=rbac_context.user_id)
                return {
                    "resolved_accounts": [],
                    "candidates": [],
                    "confidence": 0.0,
                    "requires_disambiguation": False,
                    "suggestions": [],
                    "error": "No accessible accounts found",
                }

            if not self.use_tfidf or not self.tfidf_filter:
                logger.warning("TF-IDF is disabled; no resolution performed", user_id=rbac_context.user_id)
                return {
                    "resolved_accounts": [],
                    "candidates": [user_query],
                    "confidence": 0.0,
                    "requires_disambiguation": False,
                    "suggestions": [],
                    "method": "tfidf",
                }

            # Ensure TF-IDF filter is fitted
            await self._ensure_tfidf_fitted(allowed_accounts, rbac_context)

            # Delegate to TF-IDF resolver
            tfidf_results = await self._resolve_with_tfidf(user_query, rbac_context)
            tfidf_results["resolved_accounts"] = list(tfidf_results.get("resolved_accounts") or [])
            return tfidf_results

        except Exception as e:
            logger.error("Failed to resolve accounts", user_id=rbac_context.user_id, error=str(e))
            raise

    async def _ensure_tfidf_fitted(self, allowed_accounts: List[Account], rbac_context: RBACContext) -> None:
        """Fit TF-IDF filter with current allowed accounts when needed."""
        try:
            cache_key = f"tfidf_fitted:{rbac_context.user_id}"
            is_fitted = await self.unified_data_service.get(cache_key)

            if not is_fitted:
                logger.info("Fitting TF-IDF filter", account_count=len(allowed_accounts))

                account_dicts = []
                for account in allowed_accounts:
                    account_dicts.append(
                        {
                            "id": account.id,
                            "name": account.name,
                            "type": getattr(account, "type", "unknown"),
                            "description": getattr(account, "description", ""),
                            "industry": getattr(account, "industry", ""),
                            "aliases": getattr(account, "aliases", []),
                        }
                    )

                self.tfidf_filter.fit(account_dicts)
                await self.unified_data_service.set(cache_key, True, ttl_seconds=3600)
                logger.info("TF-IDF filter fitted successfully")

        except Exception as e:
            logger.error("Failed to fit TF-IDF filter", error=str(e))

    async def _resolve_with_tfidf(self, user_query: str, rbac_context: RBACContext) -> Dict[str, Any]:
        """Use the TF-IDF filter to find similar accounts."""
        try:
            logger.debug("Resolving accounts with TF-IDF", user_id=rbac_context.user_id)

            similar_accounts = self.tfidf_filter.find_similar_accounts(
                query=user_query, rbac_context=rbac_context, top_k=self.max_suggestions
            )

            if not similar_accounts:
                return {
                    "resolved_accounts": [],
                    "candidates": [user_query],
                    "confidence": 0.0,
                    "requires_disambiguation": False,
                    "suggestions": [],
                    "method": "tfidf",
                }

            resolved_accounts: List[Account] = []
            suggestions = []
            confidences = []

            for acc_dict in similar_accounts:
                account = Account(
                    id=acc_dict["id"],
                    name=acc_dict["name"],
                    display_name=acc_dict["name"],
                    account_type=acc_dict.get("type", "unknown"),
                    owner_user_id="system",
                    owner_email="system@example.com",
                )
                confidence = acc_dict.get("similarity_score", 0.0)
                confidences.append(confidence)
                if confidence >= self.confidence_threshold:
                    resolved_accounts.append(account)
                else:
                    suggestions.append(
                        {
                            "account": account,
                            "confidence": confidence,
                            "method": "tfidf",
                            "explanation": acc_dict.get("explanation", {}),
                        }
                    )

            overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            requires_disambiguation = len(resolved_accounts) == 0 and len(suggestions) > 1

            result = {
                "resolved_accounts": list(resolved_accounts),
                "candidates": [user_query],
                "confidence": overall_confidence,
                "requires_disambiguation": requires_disambiguation,
                "suggestions": suggestions[: self.max_suggestions],
                "method": "tfidf",
                "tfidf_results": similar_accounts,
            }

            logger.info(
                "TF-IDF resolution completed",
                user_id=rbac_context.user_id,
                resolved_count=len(resolved_accounts),
                suggestions_count=len(suggestions),
                confidence=overall_confidence,
            )

            return result

        except Exception as e:
            logger.error("Failed to resolve with TF-IDF", error=str(e))
            return {
                "resolved_accounts": [],
                "candidates": [user_query],
                "confidence": 0.0,
                "requires_disambiguation": False,
                "suggestions": [],
                "method": "tfidf",
                "error": str(e),
            }

    async def resolve_entities(
        self,
        user_query: str,
        rbac_context: RBACContext,
        confidence_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Backwards-compatible adapter returning list of {id, name, confidence}."""
        if confidence_threshold is None:
            confidence_threshold = self.confidence_threshold

        resolution = await self.resolve_account(user_query, rbac_context)
        resolved = resolution.get("resolved_accounts") or []

        out: List[Dict[str, Any]] = []
        for acc in resolved:
            if isinstance(acc, dict):
                out.append({"id": acc.get("id"), "name": acc.get("name"), "confidence": acc.get("confidence", resolution.get("confidence", 1.0))})
            else:
                out.append({"id": getattr(acc, "id", None), "name": getattr(acc, "name", None), "confidence": getattr(acc, "confidence", resolution.get("confidence", 1.0))})

        return out

    async def resolve_account_names(
        self,
        account_names: List[str],
        rbac_context: RBACContext,
        confidence_threshold: Optional[float] = None,
    ) -> List[Account]:
        """Resolve a list of account names to Account objects using TF-IDF matching."""
        if not account_names:
            return []

        if confidence_threshold is None:
            confidence_threshold = self.confidence_threshold

        try:
            allowed_accounts = await self._get_allowed_accounts(rbac_context)

            if not allowed_accounts:
                logger.warning("No allowed accounts found for user", user_id=rbac_context.user_id)
                return []

            if self.use_tfidf and self.tfidf_filter:
                await self._ensure_tfidf_fitted(allowed_accounts, rbac_context)

            resolved_accounts: List[Account] = []

            for account_name in account_names:
                logger.debug("Resolving account name", name=account_name, user_id=rbac_context.user_id)

                best_match = None

                # Try TF-IDF resolution first
                if self.use_tfidf and self.tfidf_filter:
                    similar_accounts = self.tfidf_filter.find_similar_accounts(query=account_name, rbac_context=rbac_context, top_k=1)
                    if similar_accounts:
                        best_match_dict = similar_accounts[0]
                        best_match = Account(id=best_match_dict["id"], name=best_match_dict["name"], display_name=best_match_dict["name"], account_type=best_match_dict.get("type", "unknown"), owner_user_id="system", owner_email="system@example.com")
                        logger.info("Account resolved via TF-IDF", input_name=account_name, resolved_name=best_match.name, confidence=best_match_dict.get("similarity_score", 0.0))

                # Final fallback: fuzzy string matching
                if not best_match:
                    best_match = self._find_best_fuzzy_match(account_name, allowed_accounts)
                    if best_match:
                        logger.info("Account resolved via fuzzy matching", input_name=account_name, resolved_name=best_match.name)

                if best_match:
                    resolved_accounts.append(best_match)
                else:
                    fallback_account = allowed_accounts[0]
                    logger.warning("No good match found, using fallback account", input_name=account_name, fallback_name=fallback_account.name, user_id=rbac_context.user_id)
                    resolved_accounts.append(fallback_account)

            logger.info("Account names resolved", user_id=rbac_context.user_id, input_count=len(account_names), resolved_count=len(resolved_accounts))
            return resolved_accounts

        except Exception as e:
            logger.error("Failed to resolve account names", user_id=rbac_context.user_id, account_names=account_names, error=str(e))
            return []

    def _find_best_fuzzy_match(self, account_name: str, allowed_accounts: List[Account]) -> Optional[Account]:
        from difflib import SequenceMatcher

        best_match = None
        best_score = 0.0

        name_lower = account_name.lower()

        for account in allowed_accounts:
            if account.name.lower() == name_lower:
                return account

            if name_lower in account.name.lower() or account.name.lower() in name_lower:
                score = 0.8
            else:
                score = SequenceMatcher(None, name_lower, account.name.lower()).ratio()

            if score > best_score:
                best_score = score
                best_match = account

        return best_match if best_score > 0.3 else None

    async def _get_allowed_accounts(self, rbac_context: RBACContext) -> List[Account]:
        """Get list of accounts that the user has access to based on RBAC context."""
        try:
            # This is a simplified implementation - in a real system, this would query
            # the database/service to get accounts based on the user's permissions
            # For now, return a basic set of demo accounts
            demo_accounts = [
                Account(
                    id="1",
                    name="Microsoft Corporation",
                    display_name="Microsoft Corporation",
                    account_type="Enterprise",
                    owner_user_id=rbac_context.user_id,
                    owner_email=rbac_context.email,
                ),
                Account(
                    id="2",
                    name="Salesforce Inc",
                    display_name="Salesforce Inc",
                    account_type="Enterprise",
                    owner_user_id=rbac_context.user_id,
                    owner_email=rbac_context.email,
                ),
                Account(
                    id="3",
                    name="Amazon Web Services",
                    display_name="Amazon Web Services",
                    account_type="Enterprise",
                    owner_user_id=rbac_context.user_id,
                    owner_email=rbac_context.email,
                ),
            ]

            logger.debug(
                "Retrieved allowed accounts",
                user_id=rbac_context.user_id,
                account_count=len(demo_accounts)
            )

            return demo_accounts

        except Exception as e:
            logger.error("Failed to get allowed accounts", user_id=rbac_context.user_id, error=str(e))
            return []


class AccountResolverService_:
    """Developer helper resolver that returns a deterministic demo account set.

    This class provides a minimal, async-compatible API similar to
    `AccountResolverService.resolve_account_names` but is purposely
    simplified for local development and tests. Import this class when
    `settings.dev_mode` is enabled to avoid depending on external services
    during TF-IDF fitting or other IO.
    """

    @staticmethod
    async def get_dummy_accounts(rbac_context: RBACContext) -> List[Account]:
        demo_accounts = [
            Account(
                id="1",
                name="Microsoft Corporation",
                display_name="Microsoft Corporation",
                account_type="Enterprise",
                owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email,
            ),
            Account(
                id="2",
                name="Salesforce Inc",
                display_name="Salesforce Inc",
                account_type="Enterprise",
                owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email,
            ),
            Account(
                id="3",
                name="Amazon Web Services",
                display_name="Amazon Web Services",
                account_type="Enterprise",
                owner_user_id=rbac_context.user_id,
                owner_email=rbac_context.email,
            ),
        ]
        return demo_accounts

    @staticmethod
    async def resolve_account_names(account_names: List[str], rbac_context: RBACContext, confidence_threshold: Optional[float] = None) -> List[Account]:
        """Resolve account names using the static demo set (dev-mode).

        This mirrors the signature of `AccountResolverService.resolve_account_names` so
        it can be used as a drop-in replacement in development.
        """
        dummy = await AccountResolverService_.get_dummy_accounts(rbac_context)
        # Try to match by simple substring or exact match
        resolved: List[Account] = []
        for name in account_names:
            found = None
            lname = (name or "").lower()
            for acc in dummy:
                if acc.name.lower() == lname or lname in acc.name.lower() or acc.name.lower() in lname:
                    found = acc
                    break
            if found:
                resolved.append(found)
            else:
                # fallback to first demo account
                resolved.append(dummy[0])

        return resolved