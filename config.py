"""
config.py — paths, thresholds, category maps, genre keywords.
All other modules import from here; nothing is imported from other modules.
"""

from pathlib import Path

# -- Library availability flags -----------------------------------------------
try:
    import ebooklib
    from ebooklib import epub as _epub
    EBOOKLIB_OK = True
except ImportError:
    EBOOKLIB_OK = False

try:
    import fitz  # pymupdf
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    import mobi as _mobi
    MOBI_OK = True
except ImportError:
    MOBI_OK = False

try:
    import isbnlib
    ISBNLIB_OK = True
except ImportError:
    ISBNLIB_OK = False

try:
    from langdetect import detect as _langdetect
    LANGDETECT_OK = True
except ImportError:
    LANGDETECT_OK = False

# Ollama is accessed via plain HTTP (stdlib only)
OLLAMA_OK = True  # verified at startup via health check

# -- Paths --------------------------------------------------------------------
BOOKS_DIR     = Path.home() / "Documents" / "Books"
ORGANIZED_DIR = BOOKS_DIR / "books_organized"
CACHE_DB      = ORGANIZED_DIR / ".cache.db"
UNCERTAIN_CSV = ORGANIZED_DIR / "uncertain_books.csv"
FAILED_DIR    = ORGANIZED_DIR / "failed"
REPROCESS_DIR = BOOKS_DIR / "___to_reprocess"

SUPPORTED_EXTS = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".cbz", ".cbr", ".fb2"}

# -- Thresholds ---------------------------------------------------------------
OLLAMA_THRESHOLD    = 75   # below this → send to Ollama for reclassification
UNCERTAIN_THRESHOLD = 55   # below this → flag in summary report
CSV_LOG_THRESHOLD   = 35   # below this AND no proper category → write to CSV

# -- Ollama -------------------------------------------------------------------
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "gpt-oss:20b"
DEFAULT_WORKERS = 10   # concurrent workers; good default for Apple Silicon

# -- Language map -------------------------------------------------------------
# Keys are ISO 639-1 (2-letter, used by Google Books) and ISO 639-2 (3-letter,
# used by Open Library and some epub metadata). Values are the folder/DB name.
LANGUAGE_MAP = {
    # English
    "en":  "english",  "eng": "english",
    # Spanish
    "es":  "spanish",  "spa": "spanish",
    # French
    "fr":  "french",   "fre": "french",   "fra": "french",
    # German
    "de":  "german",   "ger": "german",   "deu": "german",
    # Chinese (Mandarin — simplified & traditional share the same folder)
    "zh":  "chinese",  "chi": "chinese",  "zho": "chinese",
    # Portuguese
    "pt":  "portuguese", "por": "portuguese",
    # Russian
    "ru":  "russian",  "rus": "russian",
    # Japanese
    "ja":  "japanese", "jpn": "japanese",
    # Arabic
    "ar":  "arabic",   "ara": "arabic",
    # Hindi
    "hi":  "hindi",    "hin": "hindi",
    # Italian
    "it":  "italian",  "ita": "italian",
    # Korean
    "ko":  "korean",   "kor": "korean",
    # Dutch
    "nl":  "dutch",    "dut": "dutch",    "nld": "dutch",
    # Polish
    "pl":  "polish",   "pol": "polish",
    # Bengali
    "bn":  "bengali",  "ben": "bengali",
    # Czech
    "cs":  "czech",    "cze": "czech",    "ces": "czech",
}

# -- Categories ---------------------------------------------------------------
MAIN_CATEGORIES = [
    "cookbooks",
    "reading",
    "home_improvement",
    "sport_workout_yoga_health",
    "psychology",
    "leadership",
    "politics",
    "history",
    "textbook",
    "other",
]

GENRE_TO_CATEGORY = {
    "cookbooks": "cookbooks", "cooking": "cookbooks", "food": "cookbooks",
    "baking": "cookbooks", "culinary": "cookbooks",
    "fiction": "reading", "thriller": "reading", "mystery": "reading",
    "sci-fi": "reading", "fantasy": "reading", "romance": "reading",
    "horror": "reading", "biography": "reading",
    "science": "reading", "business": "reading", "self-help": "reading",
    "children": "reading", "travel": "reading", "comics": "reading",
    "poetry": "reading", "philosophy": "reading",
    "economics": "reading", "religion": "reading",
    "humor": "reading",
    "diy": "home_improvement", "home improvement": "home_improvement",
    "woodworking": "home_improvement", "gardening": "home_improvement",
    "crafts": "home_improvement", "interior design": "home_improvement",
    "architecture": "home_improvement", "renovation": "home_improvement",
    "sport": "sport_workout_yoga_health", "fitness": "sport_workout_yoga_health",
    "yoga": "sport_workout_yoga_health", "workout": "sport_workout_yoga_health",
    "health": "sport_workout_yoga_health", "nutrition": "sport_workout_yoga_health",
    "wellness": "sport_workout_yoga_health", "meditation": "sport_workout_yoga_health",
    "running": "sport_workout_yoga_health", "cycling": "sport_workout_yoga_health",
    "swimming": "sport_workout_yoga_health", "football": "sport_workout_yoga_health",
    "basketball": "sport_workout_yoga_health", "tennis": "sport_workout_yoga_health",
    "martial arts": "sport_workout_yoga_health",
    # -- new dedicated categories --
    "psychology": "psychology", "cognitive": "psychology", "behaviour": "psychology",
    "behavioral science": "psychology", "psychiatry": "psychology",
    "leadership": "leadership", "management": "leadership", "executive": "leadership",
    "team building": "leadership", "organizational": "leadership",
    "politics": "politics", "democracy": "politics", "government": "politics",
    "policy": "politics", "political science": "politics", "geopolitics": "politics",
    "history": "history", "historical": "history", "ancient history": "history",
    "world history": "history", "military history": "history",
    "textbook": "textbook", "study": "textbook", "academic": "textbook",
    "education": "textbook", "course": "textbook", "university": "textbook",
    "mathematics": "textbook", "physics": "textbook", "chemistry": "textbook",
    "biology": "textbook", "engineering": "textbook",
}

GENRE_KEYWORDS = {
    "cookbooks":        ["cookbook", "cooking", "recipes", "cuisine", "baking", "chef",
                         "gastronomy", "kookboek", "rezept", "cocina", "kitchen",
                         "pastry", "grilling", "vegan", "vegetarian"],
    "home improvement": ["diy", "do it yourself", "home improvement", "woodworking",
                         "repair", "crafts", "make your own", "knitting", "sewing",
                         "gardening", "plumbing", "building", "construction",
                         "handmade", "renovation", "interior design"],
    "sport":            ["sport", "football", "soccer", "basketball", "tennis",
                         "cycling", "marathon", "athletics", "running", "baseball",
                         "rugby", "golf", "hockey", "surfing", "martial arts"],
    "fitness":          ["fitness", "workout", "gym", "training", "weightlifting",
                         "crossfit", "bodybuilding"],
    "yoga":             ["yoga", "pilates", "stretching", "flexibility"],
    "health":           ["health", "nutrition", "wellness", "diet", "medicine",
                         "anatomy", "mental health"],
    "meditation":       ["meditation", "mindfulness", "breathing", "chakra"],
    "thriller":         ["thriller", "mystery", "detective", "crime", "suspense", "noir"],
    "sci-fi":           ["science fiction", "sci-fi", "scifi", "space opera",
                         "cyberpunk", "dystopia", "futuristic", "aliens"],
    "fantasy":          ["fantasy", "magic", "wizard", "dragon", "elves", "tolkien"],
    "romance":          ["romance", "love story", "romantic"],
    "horror":           ["horror", "scary", "haunted", "ghost"],
    "biography":        ["biography", "memoir", "autobiography", "life of", "biografie"],
    "history":          ["history", "historical", "wwii", "ancient", "medieval", "empire"],
    "science":          ["physics", "biology", "chemistry", "mathematics", "astronomy",
                         "neuroscience"],
    "business":         ["business", "entrepreneur", "management", "investing",
                         "startup", "leadership", "marketing"],
    "self-help":        ["self-help", "self help", "productivity", "motivation",
                         "habit", "mindset"],
    "children":         ["children", "kids", "fairy tale", "picture book"],
    "travel":           ["travel", "guide", "journey", "explore", "backpacking"],
    "comics":           ["comics", "graphic novel", "manga", "cartoon", "superhero"],
    "philosophy":       ["philosophy", "ethics", "existentialism", "plato", "nietzsche"],
    "psychology":       ["psychology", "cognitive", "behaviour", "freud", "jung"],
    "politics":         ["politics", "democracy", "government", "policy", "political"],
    "economics":        ["economics", "economy", "macroeconomics", "microeconomics"],
    "religion":         ["religion", "bible", "quran", "spirituality", "faith", "theology"],
    "humor":            ["humor", "comedy", "satire", "funny", "jokes"],
    "psychology":       ["psychology", "cognitive", "behaviour", "freud", "jung",
                         "psychotherapy", "mental health", "neuroscience", "behavioral",
                         "unconscious", "therapy", "counseling"],
    "leadership":       ["leadership", "leader", "management", "executive", "ceo",
                         "team", "organizational", "strategy", "mentor", "coaching",
                         "inspire", "visionary"],
    "politics":         ["politics", "democracy", "government", "policy", "political",
                         "election", "congress", "parliament", "geopolitics", "diplomacy",
                         "republic", "senate", "constitution"],
    "history":          ["history", "historical", "wwii", "world war", "ancient",
                         "medieval", "empire", "revolution", "civilization", "century",
                         "chronicle", "dynasty", "archaeology"],
    "textbook":         ["textbook", "introduction to", "fundamentals of", "principles of",
                         "lecture", "university", "academic", "course", "curriculum",
                         "calculus", "algebra", "statistics", "biology", "chemistry",
                         "physics", "engineering", "computer science"],
}

SUBJECT_GENRE_MAP = {
    "cooking": "cookbooks", "cookbooks": "cookbooks", "baking": "cookbooks",
    "food": "cookbooks", "culinary": "cookbooks",
    "fiction": "fiction", "thriller": "thriller", "mystery": "thriller",
    "crime": "thriller", "science fiction": "sci-fi", "fantasy": "fantasy",
    "romance": "romance", "horror": "horror", "biography": "biography",
    "history": "history", "sports": "sport", "sport": "sport",
    "fitness": "fitness", "yoga": "yoga", "health": "health",
    "wellness": "health", "nutrition": "health",
    "crafts": "home improvement", "hobbies": "home improvement",
    "house": "home improvement", "home": "home improvement",
    "gardening": "home improvement", "woodworking": "home improvement",
    "self-help": "self-help", "psychology": "psychology",
    "philosophy": "philosophy", "business": "business",
    "economics": "economics", "politics": "politics",
    "travel": "travel", "comics": "comics", "children": "children",
    "religion": "religion",
    "leadership": "leadership", "management": "leadership",
    "history": "history", "historical": "history",
    "textbook": "textbook", "education": "textbook", "academic": "textbook",
    "mathematics": "textbook", "physics": "textbook",
    "chemistry": "textbook", "biology": "textbook", "engineering": "textbook",
}
