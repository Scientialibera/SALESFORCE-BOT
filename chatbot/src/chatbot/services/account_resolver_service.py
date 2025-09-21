"""
Account resolver service for entity extraction and disambiguation.

This service extracts account names from user queries and resolves them
to canonical account IDs using both LLM-based extraction and TF-IDF similarity matching.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
import structlog

from chatbot.agents.filters.account_resolver_filter import AccountResolverFilter
from chatbot.clients.aoai_client import AzureOpenAIClient
from chatbot.models.account import Account
from chatbot.models.rbac import RBACContext
from chatbot.repositories.cache_repository import CacheRepository
from chatbot.utils.embeddings import compute_cosine_similarity, get_embedding

logger = structlog.get_logger(__name__)


class AccountResolverService:
    """Service for resolving account names from user queries using TF-IDF and embeddings."""
    
    def __init__(
        self,
        aoai_client: AzureOpenAIClient,
        cache_repository: CacheRepository,
        confidence_threshold: float = 0.8,
        max_suggestions: int = 3,
        tfidf_threshold: float = 0.3,
        use_tfidf: bool = True
    ):
        """
        Initialize the account resolver service.
        
        Args:
            aoai_client: Azure OpenAI client for embeddings and LLM
            cache_repository: Cache repository for storing embeddings
            confidence_threshold: Minimum confidence for automatic resolution
            max_suggestions: Maximum number of suggestions to return
            tfidf_threshold: Minimum TF-IDF similarity for matches
            use_tfidf: Whether to use TF-IDF filtering (preferred method)
        """
        self.aoai_client = aoai_client
        self.cache_repository = cache_repository
        self.confidence_threshold = confidence_threshold
        self.max_suggestions = max_suggestions
        self.use_tfidf = use_tfidf
        
        # Initialize TF-IDF filter if enabled
        self.tfidf_filter = None
        if use_tfidf:
            self.tfidf_filter = AccountResolverFilter(
                min_similarity=tfidf_threshold,
                max_candidates=max_suggestions * 2  # Get more candidates for better results
            )
            
        logger.info(
            "Account resolver service initialized",
            use_tfidf=use_tfidf,
            confidence_threshold=confidence_threshold,
            tfidf_threshold=tfidf_threshold
        )
        
    async def resolve_account(
        self,
        user_query: str,
        rbac_context: RBACContext,
        allowed_accounts: Optional[List[Account]] = None
    ) -> Dict[str, Any]:
        """
        Resolve account names from user query using TF-IDF and embeddings.
        
        Args:
            user_query: User's natural language query
            rbac_context: User's RBAC context for filtering allowed accounts
            allowed_accounts: Optional list of allowed accounts (will fetch if not provided)
            
        Returns:
            Dictionary with resolution results
        """
        try:
            logger.info(
                "Starting account resolution",
                user_id=rbac_context.user_id,
                query_length=len(user_query),
                use_tfidf=self.use_tfidf
            )
            
            # Step 1: Get allowed accounts for user
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
                    "error": "No accessible accounts found"
                }
            
            # Step 2: Initialize TF-IDF filter if not already done
            if self.use_tfidf and self.tfidf_filter:
                await self._ensure_tfidf_fitted(allowed_accounts, rbac_context)
            
            # Step 3: Try TF-IDF resolution first (if enabled)
            if self.use_tfidf and self.tfidf_filter:
                tfidf_results = await self._resolve_with_tfidf(user_query, rbac_context)
                
                # If TF-IDF gives good results, use them
                if tfidf_results and tfidf_results.get("confidence", 0) >= self.confidence_threshold:
                    logger.info(
                        "High confidence TF-IDF resolution",
                        user_id=rbac_context.user_id,
                        confidence=tfidf_results["confidence"],
                        resolved_count=len(tfidf_results["resolved_accounts"])
                    )
                    return tfidf_results
            
            # Step 4: Fallback to LLM + embedding approach
            llm_results = await self._resolve_with_llm_embeddings(
                user_query, rbac_context, allowed_accounts
            )
            
            # Step 5: Combine results if both methods were used
            if self.use_tfidf and self.tfidf_filter and tfidf_results:
                combined_results = await self._combine_resolution_results(
                    tfidf_results, llm_results, user_query
                )
                return combined_results
            
            return llm_results
            
        except Exception as e:
            logger.error(
                "Failed to resolve accounts",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def _ensure_tfidf_fitted(self, allowed_accounts: List[Account], rbac_context: RBACContext) -> None:
        """
        Ensure TF-IDF filter is fitted with current accounts.
        
        Args:
            allowed_accounts: List of accounts to fit
            rbac_context: User's RBAC context
        """
        try:
            # Check if we need to refit (cache-based check)
            cache_key = f"tfidf_fitted:{rbac_context.user_id}"
            is_fitted = await self.cache_repository.get(cache_key)
            
            if not is_fitted:
                logger.info("Fitting TF-IDF filter", account_count=len(allowed_accounts))
                
                # Convert accounts to dictionary format for TF-IDF filter
                account_dicts = []
                for account in allowed_accounts:
                    account_dict = {
                        'id': account.id,
                        'name': account.name,
                        'type': getattr(account, 'type', 'unknown'),
                        'description': getattr(account, 'description', ''),
                        'industry': getattr(account, 'industry', ''),
                        'aliases': getattr(account, 'aliases', [])
                    }
                    account_dicts.append(account_dict)
                
                # Fit the TF-IDF vectorizer
                self.tfidf_filter.fit(account_dicts)
                
                # Cache that we've fitted (expires in 1 hour)
                await self.cache_repository.set(cache_key, True, ttl_seconds=3600)
                
                logger.info("TF-IDF filter fitted successfully")
                
        except Exception as e:
            logger.error("Failed to fit TF-IDF filter", error=str(e))
            # Continue without TF-IDF if fitting fails
    
    async def _resolve_with_tfidf(self, user_query: str, rbac_context: RBACContext) -> Dict[str, Any]:
        """
        Resolve accounts using TF-IDF similarity.
        
        Args:
            user_query: User's natural language query
            rbac_context: User's RBAC context
            
        Returns:
            Resolution results using TF-IDF
        """
        try:
            logger.debug("Resolving accounts with TF-IDF", user_id=rbac_context.user_id)
            
            # Use TF-IDF filter to find similar accounts
            similar_accounts = self.tfidf_filter.find_similar_accounts(
                query=user_query,
                rbac_context=rbac_context,
                top_k=self.max_suggestions
            )
            
            if not similar_accounts:
                return {
                    "resolved_accounts": [],
                    "candidates": [user_query],
                    "confidence": 0.0,
                    "requires_disambiguation": False,
                    "suggestions": [],
                    "method": "tfidf"
                }
            
            # Convert back to Account objects and calculate overall confidence
            resolved_accounts = []
            suggestions = []
            confidences = []
            
            for acc_dict in similar_accounts:
                account = Account(
                    id=acc_dict['id'],
                    name=acc_dict['name'],
                    display_name=acc_dict['name'],
                    account_type=acc_dict.get('type', 'unknown'),
                    owner_user_id='system',
                    owner_email='system@example.com'
                )
                
                confidence = acc_dict.get('similarity_score', 0.0)
                confidences.append(confidence)
                
                if confidence >= self.confidence_threshold:
                    resolved_accounts.append(account)
                else:
                    suggestions.append({
                        "account": account,
                        "confidence": confidence,
                        "method": "tfidf",
                        "explanation": acc_dict.get('explanation', {})
                    })
            
            overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            requires_disambiguation = len(resolved_accounts) == 0 and len(suggestions) > 1
            
            result = {
                "resolved_accounts": resolved_accounts,
                "candidates": [user_query],
                "confidence": overall_confidence,
                "requires_disambiguation": requires_disambiguation,
                "suggestions": suggestions[:self.max_suggestions],
                "method": "tfidf",
                "tfidf_results": similar_accounts
            }
            
            logger.info(
                "TF-IDF resolution completed",
                user_id=rbac_context.user_id,
                resolved_count=len(resolved_accounts),
                suggestions_count=len(suggestions),
                confidence=overall_confidence
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
                "error": str(e)
            }
    
    async def _resolve_with_llm_embeddings(
        self,
        user_query: str,
        rbac_context: RBACContext,
        allowed_accounts: List[Account]
    ) -> Dict[str, Any]:
        """
        Resolve accounts using LLM extraction + embedding similarity.
        
        Args:
            user_query: User's natural language query
            rbac_context: User's RBAC context
            allowed_accounts: List of allowed accounts
            
        Returns:
            Resolution results using LLM + embeddings
        """
        try:
            logger.debug("Resolving accounts with LLM + embeddings", user_id=rbac_context.user_id)
            
            # Step 1: Extract candidate account names from query
            candidate_names = await self._extract_account_candidates(user_query)
            
            if not candidate_names:
                return {
                    "resolved_accounts": [],
                    "candidates": [],
                    "confidence": 0.0,
                    "requires_disambiguation": False,
                    "suggestions": [],
                    "method": "llm_embeddings"
                }
            
            # Step 2: Resolve candidates using embedding similarity
            resolution_results = []
            
            for candidate in candidate_names:
                matches = await self._find_similar_accounts(candidate, allowed_accounts)
                if matches:
                    resolution_results.append({
                        "candidate": candidate,
                        "matches": matches,
                        "best_match": matches[0] if matches else None
                    })
            
            # Step 3: Determine if disambiguation is needed
            high_confidence_matches = []
            requires_disambiguation = False
            suggestions = []
            
            for result in resolution_results:
                best_match = result["best_match"]
                if best_match and best_match["confidence"] >= self.confidence_threshold:
                    high_confidence_matches.append(best_match["account"])
                else:
                    requires_disambiguation = True
                    # Add top suggestions for disambiguation
                    suggestions.extend(result["matches"][:self.max_suggestions])
            
            overall_confidence = (
                sum(r["best_match"]["confidence"] for r in resolution_results if r["best_match"])
                / len(resolution_results)
            ) if resolution_results else 0.0
            
            result = {
                "resolved_accounts": high_confidence_matches,
                "candidates": candidate_names,
                "confidence": overall_confidence,
                "requires_disambiguation": requires_disambiguation,
                "suggestions": suggestions[:self.max_suggestions],
                "resolution_details": resolution_results,
                "method": "llm_embeddings"
            }
            
            logger.info(
                "LLM + embeddings resolution completed",
                user_id=rbac_context.user_id,
                candidates_count=len(candidate_names),
                resolved_count=len(high_confidence_matches),
                requires_disambiguation=requires_disambiguation,
                confidence=overall_confidence
            )
            
            return result
            
        except Exception as e:
            logger.error("Failed to resolve with LLM + embeddings", error=str(e))
            raise
    
    async def _combine_resolution_results(
        self,
        tfidf_results: Dict[str, Any],
        llm_results: Dict[str, Any],
        user_query: str
    ) -> Dict[str, Any]:
        """
        Combine TF-IDF and LLM resolution results.
        
        Args:
            tfidf_results: Results from TF-IDF method
            llm_results: Results from LLM + embeddings method
            user_query: Original user query
            
        Returns:
            Combined resolution results
        """
        try:
            # Use TF-IDF results as primary if confidence is good
            if tfidf_results.get("confidence", 0) >= self.confidence_threshold * 0.8:
                primary_results = tfidf_results
                secondary_results = llm_results
                method = "tfidf_primary"
            else:
                primary_results = llm_results
                secondary_results = tfidf_results
                method = "llm_primary"
            
            # Merge suggestions from both methods
            combined_suggestions = []
            seen_account_ids = set()
            
            # Add primary suggestions
            for suggestion in primary_results.get("suggestions", []):
                account = suggestion.get("account")
                if account and account.id not in seen_account_ids:
                    combined_suggestions.append(suggestion)
                    seen_account_ids.add(account.id)
            
            # Add secondary suggestions if we have room
            for suggestion in secondary_results.get("suggestions", []):
                if len(combined_suggestions) >= self.max_suggestions:
                    break
                account = suggestion.get("account")
                if account and account.id not in seen_account_ids:
                    combined_suggestions.append(suggestion)
                    seen_account_ids.add(account.id)
            
            # Combine resolved accounts (prefer primary)
            resolved_accounts = primary_results.get("resolved_accounts", [])
            if not resolved_accounts:
                resolved_accounts = secondary_results.get("resolved_accounts", [])
            
            # Calculate combined confidence
            primary_confidence = primary_results.get("confidence", 0.0)
            secondary_confidence = secondary_results.get("confidence", 0.0)
            combined_confidence = max(primary_confidence, secondary_confidence * 0.8)
            
            result = {
                "resolved_accounts": resolved_accounts,
                "candidates": primary_results.get("candidates", [user_query]),
                "confidence": combined_confidence,
                "requires_disambiguation": primary_results.get("requires_disambiguation", False),
                "suggestions": combined_suggestions[:self.max_suggestions],
                "method": method,
                "primary_method": primary_results.get("method", "unknown"),
                "secondary_method": secondary_results.get("method", "unknown"),
                "tfidf_results": tfidf_results,
                "llm_results": llm_results
            }
            
            logger.info(
                "Combined resolution results",
                method=method,
                combined_confidence=combined_confidence,
                resolved_count=len(resolved_accounts),
                suggestions_count=len(combined_suggestions)
            )
            
            return result
            
        except Exception as e:
            logger.error("Failed to combine resolution results", error=str(e))
            # Return primary results as fallback
            return tfidf_results if tfidf_results.get("confidence", 0) > llm_results.get("confidence", 0) else llm_results
    
    async def explain_account_match(
        self,
        user_query: str,
        account: Account,
        rbac_context: RBACContext
    ) -> Dict[str, Any]:
        """
        Explain why an account matched the user query.
        
        Args:
            user_query: Original user query
            account: Matched account
            rbac_context: User's RBAC context
            
        Returns:
            Explanation of the match
        """
        try:
            explanations = {}
            
            # Get TF-IDF explanation if available
            if self.use_tfidf and self.tfidf_filter:
                account_dict = {
                    'id': account.id,
                    'name': account.name,
                    'type': getattr(account, 'type', 'unknown')
                }
                tfidf_explanation = self.tfidf_filter.explain_match(user_query, account_dict)
                explanations['tfidf'] = tfidf_explanation
            
            # Get embedding-based explanation
            candidate_names = await self._extract_account_candidates(user_query)
            if candidate_names:
                # Find the best matching candidate
                best_candidate = None
                best_similarity = 0.0
                
                for candidate in candidate_names:
                    candidate_embedding = await self._get_cached_embedding(candidate)
                    account_embedding = await self._get_cached_embedding(account.name)
                    
                    if candidate_embedding and account_embedding:
                        similarity = compute_cosine_similarity(candidate_embedding, account_embedding)
                        if similarity > best_similarity:
                            best_similarity = similarity
                            best_candidate = candidate
                
                explanations['embeddings'] = {
                    'best_candidate': best_candidate,
                    'similarity_score': best_similarity,
                    'extracted_candidates': candidate_names
                }
            
            return {
                'query': user_query,
                'account': {
                    'id': account.id,
                    'name': account.name,
                    'type': getattr(account, 'type', 'unknown')
                },
                'explanations': explanations,
                'user_id': rbac_context.user_id
            }
            
        except Exception as e:
            logger.error("Failed to explain account match", error=str(e))
            return {'error': str(e)}
    
    async def _extract_account_candidates(self, user_query: str) -> List[str]:
        """
        Extract potential account names from user query using LLM.
        Extract potential account names from user query using LLM.
        
        Args:
            user_query: User's natural language query
            
        Returns:
            List of candidate account names
        """
        try:
            # Use LLM to extract account names
            system_prompt = """You are an expert at extracting company/account names from user queries.
            
Extract all potential company or account names mentioned in the user's query.
Return only the names, one per line, without any additional text or explanations.
Focus on proper nouns that could be company names.

Examples:
Input: "Show me sales data for Microsoft and Apple"
Output:
Microsoft
Apple

Input: "What are the quarterly results for Salesforce?"
Output:
Salesforce

Input: "Compare revenue between IBM, Google, and Amazon"
Output:
IBM
Google
Amazon"""
            
            response = await self.aoai_client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                max_tokens=200,
                temperature=0.1
            )
            
            if response and 'choices' in response and len(response['choices']) > 0:
                content = response['choices'][0]['message']['content']
                # Parse the response to extract names
                names = [
                    name.strip()
                    for name in content.strip().split('\n')
                    if name.strip() and len(name.strip()) > 1
                ]
                
                # Also try regex-based extraction as fallback
                regex_names = self._extract_names_with_regex(user_query)
                
                # Combine and deduplicate
                all_names = list(set(names + regex_names))
                
                logger.debug(
                    "Extracted account candidates",
                    llm_names=names,
                    regex_names=regex_names,
                    final_names=all_names
                )
                
                return all_names
            
            # Fallback to regex only if LLM fails
            return self._extract_names_with_regex(user_query)
            
        except Exception as e:
            logger.error("Failed to extract account candidates", error=str(e))
            # Fallback to regex extraction
            return self._extract_names_with_regex(user_query)
    
    def _extract_names_with_regex(self, user_query: str) -> List[str]:
        """
        Extract potential company names using regex patterns.
        
        Args:
            user_query: User's natural language query
            
        Returns:
            List of candidate names
        """
        # Patterns for common company name formats
        patterns = [
            r'\b[A-Z][a-zA-Z0-9&\s]{2,30}(?:\s+Inc\.?|\s+Corp\.?|\s+LLC|\s+Ltd\.?)?\b',
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b',  # Proper case words
        ]
        
        candidates = []
        for pattern in patterns:
            matches = re.findall(pattern, user_query)
            candidates.extend(matches)
        
        # Filter out common words that aren't company names
        stop_words = {
            'Show', 'What', 'How', 'When', 'Where', 'Why', 'Who', 'Which',
            'Can', 'Could', 'Would', 'Should', 'The', 'This', 'That',
            'For', 'From', 'With', 'About', 'Between', 'Compare', 'Data'
        }
        
        filtered_candidates = [
            name.strip()
            for name in candidates
            if name.strip() not in stop_words and len(name.strip()) > 2
        ]
        
        return list(set(filtered_candidates))
    
    async def _get_allowed_accounts(self, rbac_context: RBACContext) -> List[Account]:
        """
        Get list of accounts accessible to the user.
        
        Args:
            rbac_context: User's RBAC context
            
        Returns:
            List of allowed accounts
        """
        try:
            # Check cache first
            cache_key = f"allowed_accounts:{rbac_context.user_id}"
            cached_accounts = await self.cache_repository.get(cache_key)
            
            if cached_accounts:
                logger.debug("Using cached allowed accounts", user_id=rbac_context.user_id)
                return [Account(**acc) for acc in cached_accounts]
            
            # TODO: Implement actual account fetching from SQL schema repository
            # For now, return mock accounts based on user roles
            mock_accounts = self._get_mock_accounts_for_user(rbac_context)
            
            # Cache the results
            account_dicts = [acc.__dict__ for acc in mock_accounts]
            await self.cache_repository.set(cache_key, account_dicts, ttl_seconds=3600)
            
            return mock_accounts
            
        except Exception as e:
            logger.error(
                "Failed to get allowed accounts",
                user_id=rbac_context.user_id,
                error=str(e)
            )
            return []
    
    def _get_mock_accounts_for_user(self, rbac_context: RBACContext) -> List[Account]:
        """
        Generate mock accounts for demonstration purposes.
        
        Args:
            rbac_context: User's RBAC context
            
        Returns:
            List of mock accounts
        """
        # Generate different accounts based on user roles
        # Build fully-populated mock Account objects to satisfy pydantic validation
        from datetime import datetime
        now = datetime.utcnow()
        def mk(id, name, acct_type="enterprise", industry="Technology", description=""):
            return Account(
                id=id,
                name=name,
                display_name=name,
                account_type=acct_type,
                industry=industry,
                annual_revenue=None,
                number_of_employees=None,
                billing_address=None,
                shipping_address=None,
                phone=None,
                website=None,
                owner_user_id="owner-001",
                owner_email="owner@example.com",
                aliases=[],
                name_embedding=None,
                is_active=True,
                created_at=now,
                updated_at=now,
                sf_last_modified=None,
                sf_system_modstamp=None,
            )

        base_accounts = [
            mk("acc_salesforce", "Salesforce Inc", "enterprise", "Technology", "Customer relationship management platform"),
            mk("acc_microsoft", "Microsoft Corporation", "enterprise", "Technology", "Leading technology company specializing in software and cloud services"),
            mk("acc_oracle", "Oracle Corporation", "enterprise", "Technology", "Database software and cloud computing company"),
            mk("acc_aws", "Amazon Web Services", "enterprise", "Cloud Computing", "Global cloud infrastructure provider"),
            mk("acc_google", "Google LLC", "enterprise", "Technology", "Internet search and advertising technology company"),
            mk("acc_sap", "SAP SE", "enterprise", "Enterprise Software", "Enterprise resource planning and business software company"),
        ]
        
        # Filter based on user roles (simplified logic)
        if "admin" in rbac_context.roles:
            return base_accounts  # Admin sees all accounts
        elif "sales_manager" in rbac_context.roles:
            return base_accounts[:7]  # Manager sees most accounts
        elif "sales_rep" in rbac_context.roles:
            return base_accounts[:5]  # Rep sees fewer accounts
        else:
            return base_accounts[:3]  # Default limited access
    
    async def _find_similar_accounts(
        self,
        candidate_name: str,
        allowed_accounts: List[Account]
    ) -> List[Dict[str, Any]]:
        """
        Find accounts similar to candidate name using embeddings.
        
        Args:
            candidate_name: Candidate account name to match
            allowed_accounts: List of accounts to search
            
        Returns:
            List of similar accounts with confidence scores
        """
        try:
            # Get embedding for candidate name
            candidate_embedding = await self._get_cached_embedding(candidate_name)
            
            if not candidate_embedding:
                return []
            
            similarities = []
            
            for account in allowed_accounts:
                # Get embedding for account name
                account_embedding = await self._get_cached_embedding(account.name)
                
                if account_embedding:
                    # Compute cosine similarity
                    similarity = compute_cosine_similarity(candidate_embedding, account_embedding)
                    
                    similarities.append({
                        "account": account,
                        "confidence": similarity,
                        "candidate": candidate_name
                    })
            
            # Sort by similarity score (descending)
            similarities.sort(key=lambda x: x["confidence"], reverse=True)
            
            # Return top matches
            return similarities[:self.max_suggestions]
            
        except Exception as e:
            logger.error(
                "Failed to find similar accounts",
                candidate_name=candidate_name,
                error=str(e)
            )
            return []
    
    async def _get_cached_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get embedding for text with caching.
        
        Args:
            text: Text to get embedding for
            
        Returns:
            Embedding vector or None if failed
        """
        try:
            # Check cache first
            cache_key = f"embedding:{hash(text.lower())}"
            cached_embedding = await self.cache_repository.get(cache_key)
            
            if cached_embedding:
                return cached_embedding
            
            # Generate new embedding
            embedding = await get_embedding(text, self.aoai_client)
            
            if embedding:
                # Cache the embedding
                await self.cache_repository.set(cache_key, embedding, ttl_seconds=86400)  # 24 hours
                return embedding
            
            return None
            
        except Exception as e:
            logger.error("Failed to get embedding", text=text, error=str(e))
            return None

    # Backwards-compatible adapter expected by some agents
    async def resolve_entities(
        self,
        user_query: str,
        rbac_context: RBACContext,
        confidence_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Adapter method to provide a simple list of resolved entity dicts
        when callers (like older agents) expect `resolve_entities`.
        Returns list of {id, name, confidence}.
        """
        if confidence_threshold is None:
            confidence_threshold = self.confidence_threshold

        resolution = await self.resolve_account(user_query, rbac_context)
        resolved = resolution.get("resolved_accounts") or []

        out: List[Dict[str, Any]] = []
        for acc in resolved:
            if isinstance(acc, dict):
                out.append({
                    "id": acc.get("id"),
                    "name": acc.get("name"),
                    "confidence": acc.get("confidence", resolution.get("confidence", 1.0)),
                })
            else:
                out.append({
                    "id": getattr(acc, "id", None),
                    "name": getattr(acc, "name", None),
                    "confidence": getattr(acc, "confidence", resolution.get("confidence", 1.0)),
                })

        return out
