"""
WAMA Dev AI - Smart File Discovery

Intelligent file discovery using semantic search and pattern matching.
Finds relevant files without scanning everything.
"""

import os
import re
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict, Set, Tuple
from dataclasses import dataclass
import fnmatch

from config import (
    BASE_DIR, EXCLUDE_DIRS, CODE_EXTENSIONS, IMPORTANT_FILES,
    EMBEDDINGS_DIR, CACHE_DIR
)

# Setup logging
logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Information about a discovered file."""
    path: Path
    relative_path: Path
    size: int
    extension: str
    is_important: bool = False
    relevance_score: float = 0.0
    summary: str = ""


class FileDiscovery:
    """
    Smart file discovery for finding relevant code files.

    Features:
    - Keyword-based search (fast)
    - Semantic search with embeddings (accurate)
    - Pattern matching (glob, regex)
    - Caching for performance
    - Importance ranking
    """

    def __init__(self, llm_client=None, base_dir: Path = BASE_DIR):
        self._base_dir = base_dir
        self._llm = llm_client
        self._cache: Dict[str, List[float]] = {}
        self._file_index: Dict[str, FileInfo] = {}
        self._load_cache()

    # =========================================================================
    # Quick Search Methods (No LLM)
    # =========================================================================

    def find_by_name(self, pattern: str) -> List[FileInfo]:
        """
        Find files by name pattern (glob).

        Args:
            pattern: Glob pattern (e.g., "*.py", "views.py", "**/test_*.py")

        Returns:
            List of matching FileInfo objects
        """
        results = []

        for path in self._base_dir.rglob(pattern):
            if self._should_include(path):
                results.append(self._get_file_info(path))

        return sorted(results, key=lambda f: (not f.is_important, f.relative_path))

    def find_by_content(self, keyword: str, extensions: Optional[Set[str]] = None) -> List[FileInfo]:
        """
        Find files containing a keyword (grep-like).

        Args:
            keyword: Text to search for
            extensions: File extensions to search (default: CODE_EXTENSIONS)

        Returns:
            List of FileInfo with files containing the keyword
        """
        if extensions is None:
            extensions = CODE_EXTENSIONS

        results = []
        keyword_lower = keyword.lower()

        for ext in extensions:
            for path in self._base_dir.rglob(f"*{ext}"):
                if not self._should_include(path):
                    continue

                try:
                    content = path.read_text(encoding='utf-8', errors='ignore')
                    if keyword_lower in content.lower():
                        info = self._get_file_info(path)
                        # Count occurrences for relevance
                        info.relevance_score = content.lower().count(keyword_lower)
                        results.append(info)
                except Exception:
                    continue

        return sorted(results, key=lambda f: -f.relevance_score)

    def find_by_regex(self, pattern: str, extensions: Optional[Set[str]] = None) -> List[FileInfo]:
        """
        Find files with content matching a regex.

        Args:
            pattern: Regex pattern
            extensions: File extensions to search

        Returns:
            List of matching FileInfo objects
        """
        if extensions is None:
            extensions = CODE_EXTENSIONS

        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        results = []

        for ext in extensions:
            for path in self._base_dir.rglob(f"*{ext}"):
                if not self._should_include(path):
                    continue

                try:
                    content = path.read_text(encoding='utf-8', errors='ignore')
                    matches = regex.findall(content)
                    if matches:
                        info = self._get_file_info(path)
                        info.relevance_score = len(matches)
                        results.append(info)
                except Exception:
                    continue

        return sorted(results, key=lambda f: -f.relevance_score)

    def find_related(self, file_path: Path) -> List[FileInfo]:
        """
        Find files related to a given file (imports, references).

        Args:
            file_path: Path to the file

        Returns:
            List of related FileInfo objects
        """
        results = []

        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception:
            return results

        # Extract imports (Python)
        if file_path.suffix == '.py':
            import_pattern = r'(?:from|import)\s+([\w.]+)'
            imports = re.findall(import_pattern, content)

            for imp in imports:
                # Convert import to potential file path
                parts = imp.split('.')
                potential_paths = [
                    self._base_dir / '/'.join(parts) / '__init__.py',
                    self._base_dir / ('/'.join(parts) + '.py'),
                    self._base_dir / 'wama' / '/'.join(parts) / '__init__.py',
                    self._base_dir / 'wama' / ('/'.join(parts) + '.py'),
                ]

                for p in potential_paths:
                    if p.exists() and self._should_include(p):
                        results.append(self._get_file_info(p))
                        break

        # Extract references to other files
        file_refs = re.findall(r'["\']([^"\']+\.(?:py|js|html|css))["\']', content)
        for ref in file_refs:
            potential = self._base_dir / ref
            if potential.exists() and self._should_include(potential):
                results.append(self._get_file_info(potential))

        return list({f.path: f for f in results}.values())  # Deduplicate

    # =========================================================================
    # Semantic Search (With LLM)
    # =========================================================================

    def find_semantic(
        self,
        query: str,
        top_k: int = 10,
        extensions: Optional[Set[str]] = None
    ) -> List[FileInfo]:
        """
        Find files semantically related to a query using embeddings.

        Args:
            query: Natural language query
            top_k: Number of results to return
            extensions: File extensions to search

        Returns:
            List of FileInfo objects sorted by relevance
        """
        if self._llm is None:
            # Fallback to keyword search
            return self.find_by_content(query, extensions)[:top_k]

        if extensions is None:
            extensions = CODE_EXTENSIONS

        # Get query embedding
        query_embedding = self._llm.embed(query)

        # Get or compute file embeddings
        candidates = []
        for ext in extensions:
            for path in self._base_dir.rglob(f"*{ext}"):
                if not self._should_include(path):
                    continue

                file_embedding = self._get_file_embedding(path)
                if file_embedding:
                    similarity = self._cosine_similarity(query_embedding, file_embedding)
                    info = self._get_file_info(path)
                    info.relevance_score = similarity
                    candidates.append(info)

        # Sort by relevance and return top_k
        candidates.sort(key=lambda f: -f.relevance_score)
        return candidates[:top_k]

    def find_for_task(self, task_description: str, top_k: int = 10) -> List[FileInfo]:
        """
        Find files relevant to a task description.

        Combines keyword search with semantic search and glob patterns.

        Args:
            task_description: Description of the task
            top_k: Number of results

        Returns:
            List of relevant FileInfo objects
        """
        results = []
        seen_paths = set()

        # 1. Extract keywords and search
        keywords = self._extract_keywords(task_description)
        logger.debug(f"Keywords extracted: {keywords[:10]}")

        # 2. First, try glob patterns (for compound terms like filemanager)
        for keyword in keywords[:5]:
            if '*' in keyword:
                logger.debug(f"Glob search for: {keyword}")
                for info in self.find_by_name(keyword)[:5]:
                    if info.path not in seen_paths:
                        info.relevance_score = 100  # High priority for glob matches
                        results.append(info)
                        seen_paths.add(info.path)

        # 3. Search in paths (directory/file names) - higher priority
        for keyword in keywords[:5]:
            if '*' not in keyword:
                logger.debug(f"Path search for: {keyword}")
                for info in self.find_by_name(f"*{keyword}*")[:3]:
                    if info.path not in seen_paths:
                        info.relevance_score = 50
                        results.append(info)
                        seen_paths.add(info.path)

        # 4. Content search for remaining keywords
        for keyword in keywords[:5]:
            if '*' not in keyword:
                logger.debug(f"Content search for: {keyword}")
                for info in self.find_by_content(keyword)[:3]:
                    if info.path not in seen_paths:
                        results.append(info)
                        seen_paths.add(info.path)

        logger.debug(f"Keyword search found {len(results)} files")

        # 5. Semantic search if available and we don't have enough results
        if self._llm and len(results) < top_k:
            logger.debug("Running semantic search...")
            for info in self.find_semantic(task_description, top_k=5):
                if info.path not in seen_paths:
                    results.append(info)
                    seen_paths.add(info.path)
            logger.debug(f"After semantic search: {len(results)} files")

        # 6. Add important files that might be relevant
        for info in self._get_important_files():
            if info.path not in seen_paths:
                # Check if file name matches any keyword
                if any(kw.lower() in info.path.name.lower() for kw in keywords if '*' not in kw):
                    results.append(info)
                    seen_paths.add(info.path)

        # Sort by relevance score (higher first)
        results.sort(key=lambda f: -f.relevance_score)

        logger.debug(f"Total files found: {len(results)}")
        return results[:top_k]

    # =========================================================================
    # File Listing
    # =========================================================================

    def list_all(self, extensions: Optional[Set[str]] = None) -> List[FileInfo]:
        """List all code files in the project."""
        if extensions is None:
            extensions = CODE_EXTENSIONS

        results = []
        for ext in extensions:
            for path in self._base_dir.rglob(f"*{ext}"):
                if self._should_include(path):
                    results.append(self._get_file_info(path))

        return sorted(results, key=lambda f: f.relative_path)

    def list_directory(self, directory: Path) -> List[FileInfo]:
        """List files in a specific directory."""
        results = []

        if not directory.is_absolute():
            directory = self._base_dir / directory

        for path in directory.iterdir():
            if path.is_file() and self._should_include(path):
                results.append(self._get_file_info(path))

        return sorted(results, key=lambda f: f.relative_path)

    def get_project_structure(self) -> Dict:
        """
        Get a tree structure of the project.

        Returns:
            Nested dict representing directory structure
        """
        structure = {}

        for path in self._base_dir.rglob("*"):
            if not self._should_include(path):
                continue

            if path.is_file() and path.suffix in CODE_EXTENSIONS:
                try:
                    rel = path.relative_to(self._base_dir)
                except ValueError:
                    continue

                # Build nested structure
                current = structure
                parts = list(rel.parts)

                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]

                # Add file
                current[parts[-1]] = {
                    "type": "file",
                    "size": path.stat().st_size,
                    "ext": path.suffix,
                }

        return structure

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _should_include(self, path: Path) -> bool:
        """Check if a path should be included."""
        # Check excluded directories
        for part in path.parts:
            if part in EXCLUDE_DIRS:
                return False

        # Check extension for files
        if path.is_file():
            if path.suffix not in CODE_EXTENSIONS:
                return False

        return True

    def _get_file_info(self, path: Path) -> FileInfo:
        """Get FileInfo for a path."""
        try:
            rel_path = path.relative_to(self._base_dir)
        except ValueError:
            rel_path = path

        return FileInfo(
            path=path,
            relative_path=rel_path,
            size=path.stat().st_size if path.exists() else 0,
            extension=path.suffix,
            is_important=path.name in IMPORTANT_FILES,
        )

    def _get_important_files(self) -> List[FileInfo]:
        """Get list of important files."""
        results = []
        for name in IMPORTANT_FILES:
            for path in self._base_dir.rglob(name):
                if self._should_include(path):
                    results.append(self._get_file_info(path))
        return results

    def _get_file_embedding(self, path: Path) -> Optional[List[float]]:
        """Get or compute embedding for a file."""
        cache_key = self._get_cache_key(path)

        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
            # Truncate for embedding (max ~2000 chars for efficiency)
            content = content[:2000]

            embedding = self._llm.embed(content)
            self._cache[cache_key] = embedding
            return embedding
        except Exception:
            return None

    def _get_cache_key(self, path: Path) -> str:
        """Generate cache key for a file."""
        stat = path.stat()
        key_data = f"{path}:{stat.st_mtime}:{stat.st_size}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text, including compound terms."""
        # Common compound terms in WAMA that should stay together
        compound_terms = {
            'file manager': 'filemanager',
            'file-manager': 'filemanager',
            'filemanager': 'filemanager',
            'file_manager': 'filemanager',
            'eye tracking': 'eye_tracking',
            'eye-tracking': 'eye_tracking',
            'face analyzer': 'face_analyzer',
            'face-analyzer': 'face_analyzer',
            'text to speech': 'synthesizer',
            'text-to-speech': 'synthesizer',
            'speech synthesis': 'synthesizer',
            'image generation': 'imager',
            'video generation': 'imager',
            'audio transcription': 'transcriber',
            'media description': 'describer',
        }

        text_lower = text.lower()
        keywords = []

        # First, extract compound terms
        for phrase, canonical in compound_terms.items():
            if phrase in text_lower:
                keywords.append(canonical)
                # Also add the glob pattern for directory search
                if canonical == 'filemanager':
                    keywords.append('*filemanager*')

        # Remove common words
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'can', 'to', 'of',
            'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
            'through', 'during', 'before', 'after', 'above', 'below',
            'between', 'under', 'again', 'further', 'then', 'once', 'and',
            'but', 'or', 'nor', 'so', 'yet', 'both', 'each', 'few', 'more',
            'most', 'other', 'some', 'such', 'no', 'not', 'only', 'own',
            'same', 'than', 'too', 'very', 'just', 'also', 'now', 'here',
            'there', 'when', 'where', 'why', 'how', 'all', 'any', 'this',
            'that', 'these', 'those', 'i', 'me', 'my', 'we', 'our', 'you',
            'your', 'he', 'him', 'his', 'she', 'her', 'it', 'its', 'they',
            'them', 'their', 'what', 'which', 'who', 'whom', 'add', 'want',
            'need', 'like', 'please', 'help', 'create', 'make', 'using',
            # French
            'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'et', 'ou',
            'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles',
            'ce', 'cette', 'ces', 'mon', 'ma', 'mes', 'ton', 'ta', 'tes',
            'son', 'sa', 'ses', 'notre', 'votre', 'leur', 'leurs',
            'qui', 'que', 'quoi', 'dont', 'où', 'pour', 'par', 'sur',
            'avec', 'sans', 'sous', 'dans', 'en', 'au', 'aux',
            'est', 'sont', 'être', 'avoir', 'faire', 'dit', 'fait',
            'peut', 'peux', 'veut', 'veux', 'dois', 'doit', 'ajouter',
            'vouloir', 'besoin', 'fichier', 'fichiers',
        }

        # Extract individual words
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text_lower)

        # Filter and add to keywords
        for w in words:
            if w not in stopwords and len(w) > 2 and w not in keywords:
                keywords.append(w)

        # Prioritize: compound terms first, then by frequency
        freq = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1

        # Sort non-compound keywords by frequency
        compound_kws = [k for k in keywords if k in compound_terms.values() or '*' in k]
        other_kws = [k for k in keywords if k not in compound_kws]
        other_kws = sorted(other_kws, key=lambda w: -freq.get(w, 0))

        return compound_kws + other_kws

    def _load_cache(self):
        """Load embedding cache from disk."""
        cache_file = CACHE_DIR / "embeddings_cache.json"
        if cache_file.exists():
            try:
                self._cache = json.loads(cache_file.read_text())
            except Exception:
                self._cache = {}

    def _save_cache(self):
        """Save embedding cache to disk."""
        cache_file = CACHE_DIR / "embeddings_cache.json"
        try:
            cache_file.write_text(json.dumps(self._cache))
        except Exception:
            pass
