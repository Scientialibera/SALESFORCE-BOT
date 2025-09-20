"""
Account resolver filter using TF-IDF for entity matching.

This filter implements TF-IDF vectorization for account name matching,
providing more accurate entity resolution by considering term frequency
and document frequency in the account corpus.
"""

import re
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import structlog
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer

from chatbot.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


class AccountResolverFilter:
    """
    TF-IDF based account resolver filter for enhanced entity matching.
    
    This filter uses TF-IDF vectorization combined with cosine similarity
    to find the best matching accounts from user queries.
    """
    
    def __init__(self, min_similarity: float = 0.3, max_candidates: int = 10):
        """
        Initialize the account resolver filter.
        
        Args:
            min_similarity: Minimum similarity threshold for matches
            max_candidates: Maximum number of candidate matches to return
        """
        self.min_similarity = min_similarity
        self.max_candidates = max_candidates
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.account_vectors: Optional[np.ndarray] = None
        self.account_corpus: List[str] = []
        self.account_metadata: List[Dict[str, Any]] = []
        self.stemmer = PorterStemmer()
        self._initialize_nltk()
        
        logger.info(
            "Account resolver filter initialized",
            min_similarity=min_similarity,
            max_candidates=max_candidates
        )
    
    def _initialize_nltk(self):
        """Initialize NLTK components."""
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt', quiet=True)
        
        try:
            nltk.data.find('corpora/stopwords')
        except LookupError:
            nltk.download('stopwords', quiet=True)
    
    def _preprocess_text(self, text: str) -> str:
        """
        Preprocess text for TF-IDF vectorization.
        
        Args:
            text: Raw text to preprocess
            
        Returns:
            Preprocessed text
        """
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove special characters and numbers
        text = re.sub(r'[^a-zA-Z\s]', ' ', text)
        
        # Tokenize
        tokens = word_tokenize(text)
        
        # Remove stopwords
        stop_words = set(stopwords.words('english'))
        tokens = [token for token in tokens if token not in stop_words]
        
        # Stem tokens
        tokens = [self.stemmer.stem(token) for token in tokens]
        
        # Remove empty tokens and single characters
        tokens = [token for token in tokens if len(token) > 1]
        
        return ' '.join(tokens)
    
    def fit(self, accounts: List[Dict[str, Any]]) -> None:
        """
        Fit the TF-IDF vectorizer on the account corpus.
        
        Args:
            accounts: List of account dictionaries with 'name' and other metadata
        """
        try:
            logger.info("Fitting TF-IDF vectorizer on account corpus", account_count=len(accounts))
            
            # Store account metadata
            self.account_metadata = accounts.copy()
            
            # Create corpus from account names and additional searchable fields
            self.account_corpus = []
            for account in accounts:
                # Combine account name with other searchable fields
                text_parts = []
                
                # Add account name (required)
                name = account.get('name', '')
                if name:
                    text_parts.append(str(name))
                
                # Add other relevant fields if available and not None
                description = account.get('description')
                if description and description is not None:
                    text_parts.append(str(description))
                    
                industry = account.get('industry')
                if industry and industry is not None:
                    text_parts.append(str(industry))
                    
                acct_type = account.get('type')
                if acct_type and acct_type is not None:
                    text_parts.append(str(acct_type))
                    
                aliases = account.get('aliases')
                if aliases and aliases is not None:
                    if isinstance(aliases, list):
                        # Filter out None values from aliases list
                        valid_aliases = [str(alias) for alias in aliases if alias is not None]
                        text_parts.extend(valid_aliases)
                    else:
                        text_parts.append(str(aliases))
                
                # Combine and preprocess (ensure we have at least the name)
                combined_text = ' '.join(text_parts) if text_parts else account.get('name', 'unnamed_account')
                preprocessed_text = self._preprocess_text(combined_text)
                self.account_corpus.append(preprocessed_text)
            
            # Initialize and fit TF-IDF vectorizer
            self.vectorizer = TfidfVectorizer(
                max_features=5000,  # Limit vocabulary size
                ngram_range=(1, 3),  # Use unigrams, bigrams, and trigrams
                min_df=1,  # Minimum document frequency
                max_df=0.95,  # Maximum document frequency
                sublinear_tf=True,  # Use sublinear TF scaling
                norm='l2',  # L2 normalization
                stop_words='english'  # Additional stopword removal
            )
            
            # Fit and transform the corpus
            self.account_vectors = self.vectorizer.fit_transform(self.account_corpus)
            
            # Normalize vectors for faster cosine similarity computation
            self.account_vectors = normalize(self.account_vectors, norm='l2', axis=1)
            
            logger.info(
                "TF-IDF vectorizer fitted successfully",
                vocabulary_size=len(self.vectorizer.vocabulary_),
                vector_shape=self.account_vectors.shape
            )
            
        except Exception as e:
            logger.error("Failed to fit TF-IDF vectorizer", error=str(e))
            raise
    
    def transform_query(self, query: str) -> np.ndarray:
        """
        Transform a user query into TF-IDF vector space.
        
        Args:
            query: User query string
            
        Returns:
            TF-IDF vector for the query
        """
        if not self.vectorizer:
            raise ValueError("Vectorizer not fitted. Call fit() first.")
        
        # Preprocess query
        preprocessed_query = self._preprocess_text(query)
        
        # Transform to TF-IDF vector
        query_vector = self.vectorizer.transform([preprocessed_query])
        
        # Normalize vector
        query_vector = normalize(query_vector, norm='l2', axis=1)
        
        return query_vector
    
    def find_similar_accounts(
        self,
        query: str,
        rbac_context: RBACContext,
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Find accounts similar to the query using TF-IDF similarity.
        
        Args:
            query: User query string
            rbac_context: User's RBAC context for access filtering
            top_k: Number of top results to return (defaults to max_candidates)
            
        Returns:
            List of similar accounts with similarity scores
        """
        if not self.vectorizer or self.account_vectors is None:
            logger.warning("TF-IDF vectorizer not fitted, returning empty results")
            return []
        
        try:
            top_k = top_k or self.max_candidates
            
            logger.debug(
                "Finding similar accounts",
                query=query,
                user_id=rbac_context.user_id,
                top_k=top_k
            )
            
            # Transform query to vector space
            query_vector = self.transform_query(query)
            
            # Compute cosine similarities
            similarities = cosine_similarity(query_vector, self.account_vectors).flatten()
            
            # Get indices of accounts above similarity threshold
            valid_indices = np.where(similarities >= self.min_similarity)[0]
            
            if len(valid_indices) == 0:
                logger.debug("No accounts found above similarity threshold", min_similarity=self.min_similarity)
                return []
            
            # Sort by similarity (descending)
            sorted_indices = valid_indices[np.argsort(similarities[valid_indices])[::-1]]
            
            # Limit to top_k results
            top_indices = sorted_indices[:top_k]
            
            # Build results with RBAC filtering
            results = []
            for idx in top_indices:
                account = self.account_metadata[idx].copy()
                similarity_score = float(similarities[idx])
                
                # Apply RBAC filtering
                if self._has_account_access(account, rbac_context):
                    account['similarity_score'] = similarity_score
                    account['match_type'] = 'tfidf'
                    account['preprocessed_text'] = self.account_corpus[idx]
                    results.append(account)
            
            logger.info(
                "Found similar accounts",
                query=query,
                total_candidates=len(valid_indices),
                accessible_results=len(results),
                top_similarity=results[0]['similarity_score'] if results else 0.0
            )
            
            return results
            
        except Exception as e:
            logger.error("Failed to find similar accounts", query=query, error=str(e))
            return []
    
    def _has_account_access(self, account: Dict[str, Any], rbac_context: RBACContext) -> bool:
        """
        Check if user has access to the account based on RBAC.
        
        Args:
            account: Account metadata
            rbac_context: User's RBAC context
            
        Returns:
            True if user has access, False otherwise
        """
        try:
            # If RBAC is disabled, allow access
            if not rbac_context or rbac_context.is_admin:
                return True
            
            # Check if account is in user's accessible accounts
            account_id = account.get('id')
            if account_id and rbac_context.access_scope:
                if rbac_context.access_scope.accessible_accounts:
                    return account_id in rbac_context.access_scope.accessible_accounts
                
                # If no specific account restrictions, allow access
                return True
            
            # Default to allow access if no restrictions
            return True
            
        except Exception as e:
            logger.warning("Error checking account access", account_id=account.get('id'), error=str(e))
            # Default to deny access on error
            return False
    
    def get_feature_names(self) -> List[str]:
        """
        Get the feature names from the TF-IDF vectorizer.
        
        Returns:
            List of feature names (terms)
        """
        if not self.vectorizer:
            return []
        
        return self.vectorizer.get_feature_names_out().tolist()
    
    def explain_match(self, query: str, account: Dict[str, Any]) -> Dict[str, Any]:
        """
        Explain why an account matched the query.
        
        Args:
            query: Original query
            account: Matched account
            
        Returns:
            Explanation of the match
        """
        try:
            if not self.vectorizer:
                return {"error": "Vectorizer not fitted"}
            
            # Find account index
            account_idx = None
            for idx, acc in enumerate(self.account_metadata):
                if acc.get('id') == account.get('id'):
                    account_idx = idx
                    break
            
            if account_idx is None:
                return {"error": "Account not found in corpus"}
            
            # Transform query
            query_vector = self.transform_query(query)
            account_vector = self.account_vectors[account_idx:account_idx+1]
            
            # Get feature names
            feature_names = self.get_feature_names()
            
            # Get query terms with weights
            query_features = query_vector.toarray().flatten()
            account_features = account_vector.toarray().flatten()
            
            # Find contributing terms
            contributing_terms = []
            for i, (query_weight, account_weight) in enumerate(zip(query_features, account_features)):
                if query_weight > 0 and account_weight > 0:
                    contribution = query_weight * account_weight
                    if contribution > 0.01:  # Threshold for significant contribution
                        contributing_terms.append({
                            'term': feature_names[i],
                            'query_weight': float(query_weight),
                            'account_weight': float(account_weight),
                            'contribution': float(contribution)
                        })
            
            # Sort by contribution
            contributing_terms.sort(key=lambda x: x['contribution'], reverse=True)
            
            return {
                'similarity_score': account.get('similarity_score', 0.0),
                'contributing_terms': contributing_terms[:10],  # Top 10 terms
                'query_preprocessed': self._preprocess_text(query),
                'account_preprocessed': self.account_corpus[account_idx]
            }
            
        except Exception as e:
            logger.error("Failed to explain match", error=str(e))
            return {"error": str(e)}
    
    def update_account_corpus(self, new_accounts: List[Dict[str, Any]]) -> None:
        """
        Update the account corpus with new accounts and refit the vectorizer.
        
        Args:
            new_accounts: List of new account dictionaries
        """
        try:
            logger.info("Updating account corpus", new_accounts_count=len(new_accounts))
            
            # Combine existing and new accounts
            all_accounts = self.account_metadata + new_accounts
            
            # Refit the vectorizer
            self.fit(all_accounts)
            
            logger.info("Account corpus updated successfully", total_accounts=len(all_accounts))
            
        except Exception as e:
            logger.error("Failed to update account corpus", error=str(e))
            raise
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the current TF-IDF model.
        
        Returns:
            Dictionary with model statistics
        """
        if not self.vectorizer or self.account_vectors is None:
            return {"status": "not_fitted"}
        
        return {
            "status": "fitted",
            "account_count": len(self.account_metadata),
            "vocabulary_size": len(self.vectorizer.vocabulary_),
            "vector_shape": self.account_vectors.shape,
            "min_similarity": self.min_similarity,
            "max_candidates": self.max_candidates,
            "ngram_range": self.vectorizer.ngram_range,
            "max_features": self.vectorizer.max_features
        }
