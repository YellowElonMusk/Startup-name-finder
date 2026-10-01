"""Seed-word inspiration: related concepts and startup-naming "vibes".

Seed words are treated as a theme, not as literal building blocks. Each seed
is expanded through a small built-in lexicon (English synonyms plus Latin and
Greek roots), and each *vibe* turns that concept pool into names following a
well-known startup naming trend (person names like Alan, coined words like
Tinder, Latin/Greek roots like Veritas, ...).

Everything here is offline and deterministic for a given ``salt``. An optional
LLM (see ``ai.py``) can add richer, open-vocabulary ideas on top.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .phonetics import jaro_winkler_similarity

__all__ = [
    "VIBES",
    "Idea",
    "Concepts",
    "expand",
    "brand_score",
    "ideas_for",
]


@dataclass(frozen=True)
class Vibe:
    key: str
    label: str
    examples: str
    blurb: str


VIBES: dict[str, Vibe] = {v.key: v for v in (
    Vibe("human", "Human name", "Alan, Oscar, Alfred, Clara",
         "A friendly first name that makes the product feel like a person."),
    Vibe("invented", "Invented word", "Tinder, Hulu, Zillow, Kodak",
         "A short made-up word built from the sounds of your theme."),
    Vibe("classical", "Latin & Greek", "Veritas, Lumen, Nexus, Kairos",
         "Ancient roots with the same meaning as your theme."),
    Vibe("myth", "Myth & stars", "Nike, Hermes, Orion, Vega",
         "Gods, heroes and stars associated with your theme."),
    Vibe("real", "Real word", "Apple, Slack, Stripe, Notion",
         "An everyday word that works as a metaphor for the idea."),
    Vibe("compound", "Compound", "Dropbox, Snapchat, Mailchimp",
         "Two short words joined together."),
    Vibe("dropped", "Dropped vowel", "Flickr, Tumblr, Lyft, Fiverr",
         "A familiar word respelled: dropped vowels, swapped letters."),
    Vibe("suffix", "-ify / -ly", "Spotify, Calendly, Shopify",
         "A theme word plus a classic startup suffix or prefix."),
)}

DEFAULT_VIBES = ("invented", "classical", "human", "compound")


@dataclass(frozen=True)
class Idea:
    name: str
    vibe: str
    why: str = ""


@dataclass
class Concepts:
    """Expansion of the seed words into a themed vocabulary."""

    seeds: list[str]
    keys: list[str] = field(default_factory=list)       # matched lexicon concepts
    synonyms: list[str] = field(default_factory=list)
    latin: list[str] = field(default_factory=list)
    greek: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)    # seeds not in the lexicon
    gloss: dict[str, str] = field(default_factory=dict)  # word -> "Latin for light"

    def as_dict(self) -> dict:
        return {
            "seeds": self.seeds, "concepts": self.keys, "synonyms": self.synonyms,
            "latin": self.latin, "greek": self.greek, "unknown": self.unknown,
        }


# ---------------------------------------------------------------------------
# Lexicon: concept -> (english related words, latin, greek). ASCII only.
# ---------------------------------------------------------------------------

_LEX: dict[str, tuple[str, str, str]] = {
    "space": ("cosmos orbit galaxy star rocket astro void nebula", "spatium astrum caelum stella", "kosmos aster ouranos astron"),
    "star": ("star stellar nova comet", "stella sidus astrum", "aster astron"),
    "moon": ("moon lunar crescent", "luna", "selene"),
    "sun": ("sun solar sunny ray", "sol", "helios"),
    "light": ("light glow beam ray bright shine", "lux lumen lucis clarus", "phos photon lampas"),
    "fire": ("fire flame blaze spark ember", "ignis flamma", "pyr pyros"),
    "energy": ("energy power spark charge volt pulse surge", "vis vigor potentia", "energeia dynamis"),
    "electric": ("volt amp current spark", "electrum", "elektron"),
    "water": ("water wave flow tide aqua stream", "aqua unda fluvius", "hydor"),
    "ocean": ("ocean sea tide wave deep marine", "mare oceanus pontus", "thalassa pelagos okeanos"),
    "earth": ("earth terra ground soil land globe", "terra tellus humus", "gaia chthon"),
    "air": ("air sky breeze wind cloud", "aer aura ventus", "aither pneuma"),
    "wind": ("wind breeze gust zephyr", "ventus aura", "anemos zephyros"),
    "sky": ("sky cloud azure heaven", "caelum", "ouranos aither"),
    "cloud": ("cloud nimbus vapor mist", "nubes nimbus", "nephele"),
    "nature": ("nature wild leaf grove bloom", "natura silva", "physis"),
    "green": ("green eco leaf sprout verdant", "viridis", "chloros"),
    "tree": ("tree oak root branch grove", "arbor", "dendron"),
    "leaf": ("leaf frond petal", "folium", "phyllon"),
    "flower": ("flower bloom blossom petal", "flos floris", "anthos"),
    "seed": ("seed sprout kernel", "granum germen", "spora"),
    "bird": ("bird wing feather flight", "avis ala", "ornis pteron"),
    "fast": ("fast swift rapid quick dash zoom bolt", "velox celer citus", "tachys okys"),
    "time": ("time clock moment hour era", "tempus hora aevum", "chronos kairos"),
    "life": ("life live vital alive", "vita vivus anima", "bios zoe"),
    "health": ("health well vital heal care", "salus sanitas valens", "hygieia therapeia"),
    "medicine": ("heal cure remedy care", "medicus cura remedium", "iatros pharmakon"),
    "mind": ("mind brain thought idea insight", "mens cogito ingenium", "nous psyche phren"),
    "wisdom": ("wise smart sage clever insight", "sapientia sapiens prudens", "sophia sophos"),
    "learn": ("learn study know school scholar", "scientia discere doctus schola", "gnosis mathesis episteme"),
    "book": ("book page read story write", "liber scriptum littera", "biblion graphe"),
    "word": ("word voice speak talk echo", "verbum vox lingua", "logos lexis glossa"),
    "sound": ("sound tone echo sonic", "sonus", "phone echo"),
    "music": ("music melody rhythm tune chord", "cantus carmen", "melos harmonia"),
    "art": ("art craft design create studio", "ars creare forma", "techne poiesis"),
    "build": ("build make forge craft", "fabrica struere", "tekton ergon"),
    "work": ("work task job craft labor", "opus labor opera", "ergon ponos"),
    "money": ("money cash coin fund capital pay", "pecunia nummus census", "chrema ploutos"),
    "gold": ("gold golden", "aurum", "chrysos"),
    "trade": ("trade market shop store deal bazaar", "mercatus forum merx", "agora emporion"),
    "growth": ("grow rise sprout thrive scale", "crescere augere", "auxesis"),
    "data": ("data info signal metric insight", "datum index nota", "gnosis"),
    "code": ("code logic byte pixel stack", "codex computare machina", "logos techne"),
    "connect": ("link connect mesh net bridge node", "nexus rete", "desmos syndesis"),
    "safe": ("safe guard shield vault lock armor", "tutus custos scutum", "phylax aspis"),
    "trust": ("trust true honest", "fides veritas verus", "aletheia pistis"),
    "home": ("home house nest hearth dwell", "domus casa focus", "oikos hestia"),
    "family": ("family kin clan tribe", "familia gens", "genos"),
    "friend": ("friend buddy crew circle tribe", "amicus socius", "philos koinonia"),
    "love": ("love heart kind dear", "amor cor carus", "eros agape philia"),
    "joy": ("joy happy fun play glee", "gaudium laetus ludus", "chara euphoria"),
    "peace": ("calm peace still serene zen", "pax tranquillus quies", "eirene galene"),
    "sleep": ("sleep rest dream slumber", "somnus quies", "hypnos"),
    "dream": ("dream vision reverie", "somnium visio", "oneiros"),
    "night": ("night dusk midnight", "nox noctis", "nyx"),
    "dawn": ("dawn sunrise morning", "aurora mane", "eos orthros"),
    "new": ("new fresh novel neo", "novus nova recens", "neos kainos"),
    "start": ("start begin launch origin", "initium origo", "arche genesis"),
    "future": ("future next ahead beyond", "futurus posterus", "mellon"),
    "travel": ("travel trip journey roam voyage trek", "iter via viator", "hodos poreia"),
    "path": ("path way road route trail", "via iter semita", "hodos"),
    "world": ("world globe atlas map", "orbis mundus", "kosmos oikoumene"),
    "city": ("city urban metro town", "urbs civitas", "polis"),
    "food": ("food meal feast kitchen chef bite", "cibus epulae coquus", "trophe deipnon"),
    "drink": ("drink brew sip", "potio bibere", "poton"),
    "farm": ("farm harvest field crop grain", "ager messis seges", "agros"),
    "sport": ("move fit sport run active", "motus agilis", "kinesis athlon"),
    "strength": ("strong mighty iron titan", "fortis robur", "sthenos kratos"),
    "victory": ("win victory triumph champion", "victoria triumphus", "nike"),
    "hero": ("hero brave bold valor", "virtus audax", "heros andreia"),
    "king": ("king crown chief lead", "rex regnum dux", "basileus archon"),
    "freedom": ("free liberty open", "libertas liber", "eleutheria"),
    "open": ("open clear unlock", "apertus", "anoixis"),
    "vision": ("see vision eye sight view lens", "visio oculus videre", "opsis horasis"),
    "color": ("color hue tint prism spectrum", "color", "chroma"),
    "beauty": ("beauty style chic glam grace", "pulcher forma venustas", "kallos kalos"),
    "clean": ("clean pure clear fresh", "purus mundus", "katharos"),
    "simple": ("simple easy clear lite", "simplex facilis", "haplous"),
    "intelligence": ("smart mind neural sentient", "intellectus ingenium", "nous noesis"),
    "magic": ("magic wonder spell charm", "magia mirum", "mageia thauma"),
    "idea": ("idea spark notion muse", "idea notio", "ennoia"),
    "team": ("team unity together crew", "unitas simul", "henosis"),
    "help": ("help care aid assist", "auxilium cura", "boetheia"),
    "career": ("career hire talent job", "munus opera", "ergon"),
    "legal": ("law justice fair right", "lex ius iustitia", "nomos dike"),
    "key": ("key access gate door", "clavis porta ianua", "kleis thyra"),
    "mountain": ("peak summit mountain crest", "mons culmen apex", "oros akme"),
    "rock": ("stone rock granite", "lapis saxum petra", "lithos petra"),
    "iron": ("iron steel metal forge", "ferrum", "sideros"),
    "crystal": ("gem crystal jewel diamond", "gemma crystallus", "krystallos adamas"),
    "pet": ("pet paw furry companion", "animal catulus", "zoon"),
    "child": ("kid baby little tiny", "infans puer", "pais"),
    "game": ("game play quest level", "ludus", "agon paidia"),
    "photo": ("photo image snap frame", "imago pictura", "eikon"),
    "film": ("film video reel cinema", "spectaculum", "kinema theama"),
    "car": ("drive ride auto motor wheel", "currus rota vehiculum", "trochos"),
    "flight": ("fly flight wing soar glide", "volare ala", "pteron"),
    "ship": ("sail ship harbor anchor", "navis portus", "naus"),
    "atom": ("atom quantum lab science", "scientia", "atomos episteme"),
    "math": ("count number sum metric", "numerus summa", "arithmos metron"),
    "small": ("tiny mini micro little", "parvus minimus", "mikros"),
    "big": ("big grand mega giant titan", "magnus maximus grandis", "megas titan"),
    "one": ("one first prime solo unique", "unus primus unicus", "monos protos"),
    "all": ("all omni total every", "omnis totus", "pan holos"),
    "circle": ("circle loop ring orbit cycle", "circulus orbis anulus", "kyklos"),
    "balance": ("balance harmony equal", "aequilibrium concordia", "harmonia"),
    "change": ("shift change pivot morph", "mutatio", "metabole metamorphosis"),
    "flow": ("flow stream current glide", "fluxus flumen", "rhoe"),
    "message": ("message note signal chat ping", "nuntius epistula", "angelos"),
    "event": ("party event gather fest", "festum", "symposion"),
}

_ALIASES: dict[str, str] = {
    "rocket": "space", "galaxy": "space", "cosmos": "space", "universe": "space", "planet": "space",
    "orbit": "space", "astro": "space", "solar": "sun", "lunar": "moon", "electricity": "electric",
    "battery": "energy", "charge": "energy", "sea": "ocean", "marine": "ocean", "wave": "water",
    "rain": "water", "eco": "green", "sustainable": "green", "climate": "green",
    "environment": "nature", "forest": "tree", "wood": "tree", "garden": "flower", "quick": "fast",
    "speed": "fast", "rapid": "fast", "swift": "fast", "clock": "time", "wellness": "health",
    "fitness": "sport", "gym": "sport", "doctor": "medicine", "med": "medicine", "pharma": "medicine",
    "clinic": "medicine", "brain": "mind", "think": "mind", "thought": "mind", "smart": "wisdom",
    "wise": "wisdom", "clever": "wisdom", "school": "learn", "education": "learn", "study": "learn",
    "teach": "learn", "knowledge": "learn", "read": "book", "write": "book", "story": "book",
    "speak": "word", "talk": "word", "language": "word", "voice": "sound", "audio": "sound",
    "song": "music", "design": "art", "create": "art", "creative": "art", "craft": "build",
    "make": "build", "construct": "build", "finance": "money", "pay": "money", "payment": "money",
    "bank": "money", "invest": "money", "cash": "money", "fintech": "money", "wealth": "money",
    "coin": "money", "crypto": "money", "market": "trade", "shop": "trade", "commerce": "trade",
    "store": "trade", "sell": "trade", "sales": "trade", "grow": "growth", "scale": "growth",
    "info": "data", "analytics": "data", "software": "code", "dev": "code", "developer": "code",
    "computer": "code", "tech": "code", "app": "code", "network": "connect", "link": "connect",
    "security": "safe", "secure": "safe", "protect": "safe", "privacy": "safe", "true": "trust",
    "truth": "trust", "house": "home", "community": "friend", "social": "friend", "people": "friend",
    "heart": "love", "dating": "love", "happy": "joy", "fun": "joy", "play": "game", "calm": "peace",
    "relax": "peace", "meditation": "peace", "zen": "peace", "rest": "sleep", "begin": "start",
    "launch": "start", "fresh": "new", "next": "future", "trip": "travel", "journey": "travel",
    "tour": "travel", "route": "path", "road": "path", "global": "world", "map": "world",
    "urban": "city", "eat": "food", "cook": "food", "recipe": "food", "restaurant": "food",
    "kitchen": "food", "coffee": "drink", "tea": "drink", "beverage": "drink", "agriculture": "farm",
    "harvest": "farm", "strong": "strength", "power": "strength", "win": "victory", "brave": "hero",
    "leader": "king", "lead": "king", "free": "freedom", "see": "vision", "eye": "vision",
    "style": "beauty", "fashion": "beauty", "pure": "clean", "easy": "simple", "ai": "intelligence",
    "robot": "intelligence", "ml": "intelligence", "support": "help", "care": "help", "law": "legal",
    "justice": "legal", "access": "key", "peak": "mountain", "stone": "rock", "metal": "iron",
    "steel": "iron", "gem": "crystal", "diamond": "crystal", "jewel": "crystal", "dog": "pet",
    "cat": "pet", "kid": "child", "baby": "child", "video": "film", "movie": "film", "drive": "car",
    "auto": "car", "fly": "flight", "plane": "flight", "boat": "ship", "sail": "ship",
    "science": "atom", "quantum": "atom", "number": "math", "tiny": "small", "micro": "small",
    "giant": "big", "great": "big", "first": "one", "unique": "one", "loop": "circle",
    "cycle": "circle", "harmony": "balance", "shift": "change", "stream": "flow", "chat": "message",
    "mail": "message", "email": "message", "party": "event", "job": "career", "hire": "career",
    "hiring": "career", "morning": "dawn", "sunrise": "dawn", "dark": "night",
}

# Mythological figures and stars, tagged with lexicon concepts.
_MYTH: dict[str, tuple[str, str]] = {
    "hermes": ("fast message trade travel", "Greek messenger god of speed and trade"),
    "athena": ("wisdom learn mind", "Greek goddess of wisdom"),
    "apollo": ("light music health sun", "Greek god of light, music and healing"),
    "atlas": ("world strength travel", "Titan who holds up the world"),
    "orion": ("space star hero", "the hunter constellation"),
    "iris": ("color message vision", "Greek goddess of the rainbow and messages"),
    "juno": ("family safe home", "Roman queen of the gods, protector"),
    "nike": ("victory sport", "Greek goddess of victory"),
    "helios": ("sun energy light", "Greek sun god"),
    "gaia": ("earth nature green", "Greek personification of Earth"),
    "hestia": ("home family", "Greek goddess of the hearth"),
    "demeter": ("food farm growth", "Greek goddess of harvest"),
    "hypnos": ("sleep peace", "Greek god of sleep"),
    "morpheus": ("dream sleep change", "Greek god of dreams"),
    "mnemosyne": ("data mind learn", "Greek goddess of memory"),
    "chronos": ("time", "Greek personification of time"),
    "kairos": ("time one", "Greek for the perfect moment"),
    "aether": ("sky air cloud", "the bright upper sky"),
    "nyx": ("night", "Greek goddess of night"),
    "eos": ("dawn new start", "Greek goddess of dawn"),
    "selene": ("moon night", "Greek moon goddess"),
    "zephyr": ("wind fast air", "Greek god of the west wind"),
    "prometheus": ("fire idea future", "Titan who gave fire to humanity"),
    "hephaestus": ("build iron work fire", "Greek god of the forge"),
    "asclepius": ("health medicine", "Greek god of medicine"),
    "hygieia": ("health clean", "Greek goddess of health"),
    "plutus": ("money gold", "Greek god of wealth"),
    "tyche": ("money magic", "Greek goddess of fortune"),
    "triton": ("ocean water", "Greek messenger of the sea"),
    "thor": ("strength electric", "Norse god of thunder"),
    "odin": ("wisdom king", "Norse all-father, god of wisdom"),
    "freya": ("love beauty", "Norse goddess of love"),
    "loki": ("game joy change", "Norse trickster god"),
    "vulcan": ("fire build iron", "Roman god of fire and the forge"),
    "minerva": ("wisdom learn art", "Roman goddess of wisdom"),
    "mercury": ("fast message trade", "Roman messenger god"),
    "ceres": ("food farm", "Roman goddess of grain"),
    "janus": ("start key change", "Roman god of doors and beginnings"),
    "aurora": ("dawn light new", "Roman goddess of dawn"),
    "luna": ("moon night", "Roman moon goddess"),
    "sol": ("sun energy", "Roman sun god"),
    "terra": ("earth world", "Roman Earth goddess"),
    "fortuna": ("money magic", "Roman goddess of luck"),
    "vesta": ("home fire", "Roman goddess of the hearth"),
    "flora": ("flower nature", "Roman goddess of flowers"),
    "pomona": ("food farm tree", "Roman goddess of orchards"),
    "nova": ("star new space", "a star that suddenly brightens"),
    "vega": ("star space light", "one of the brightest stars"),
    "lyra": ("music star", "the lyre constellation"),
    "altair": ("star flight bird", "the eagle star"),
    "sirius": ("star light", "the brightest star in the night sky"),
    "rigel": ("star space", "a blue supergiant in Orion"),
    "polaris": ("star path travel", "the North Star, used for navigation"),
    "castor": ("friend team", "one of the Gemini twins"),
    "artemis": ("moon sport nature", "Greek goddess of the hunt and the moon"),
    "pan": ("nature music joy", "Greek god of the wild"),
    "calliope": ("book word music", "muse of epic poetry"),
    "clio": ("book data", "muse of history"),
    "thalia": ("joy art", "muse of comedy"),
    "echo": ("sound word", "nymph whose voice repeats"),
    "phoenix": ("fire change new", "bird reborn from its ashes"),
    "pegasus": ("flight fast", "the winged horse"),
    "titan": ("big strength", "the giant elder gods"),
}

# First names, with lexicon concepts some of them evoke.
_NAMES: dict[str, str] = {
    "ada": "", "alan": "", "alba": "dawn light", "alfred": "wisdom", "alma": "life", "amos": "",
    "ari": "strength", "arlo": "", "ava": "life", "basil": "king", "bea": "joy", "bruno": "",
    "cal": "", "clara": "light clean", "cleo": "", "cora": "love", "dora": "", "eli": "",
    "ella": "light", "ember": "fire", "enzo": "home", "esme": "love", "ezra": "help", "felix": "joy",
    "fern": "leaf nature", "finn": "", "flo": "flower flow", "gus": "", "hana": "flower",
    "harvey": "", "hazel": "tree nature", "hugo": "mind", "ida": "work", "iris": "vision color",
    "isla": "ocean", "ivy": "leaf nature", "jade": "crystal", "jasper": "crystal", "jude": "",
    "juno": "", "kai": "ocean", "kit": "", "lana": "", "leo": "strength king", "lila": "",
    "lola": "", "luca": "light", "lucy": "light", "luna": "moon", "mae": "", "maia": "",
    "max": "big", "milo": "", "mira": "vision", "nell": "light", "nia": "", "nico": "victory",
    "nina": "", "noa": "", "nora": "light", "olive": "peace tree", "oona": "one", "oscar": "",
    "otis": "", "otto": "money", "pia": "", "remy": "", "rex": "king", "rio": "water flow",
    "rosa": "flower", "ruby": "crystal", "rumi": "", "ruth": "friend", "sage": "wisdom",
    "sami": "", "sol": "sun", "sophia": "wisdom", "tara": "star", "tess": "", "theo": "",
    "uma": "", "vera": "trust", "vida": "life", "wren": "bird", "yara": "", "zara": "",
    "zeno": "", "felicity": "joy", "hope": "", "joy": "joy", "faith": "trust", "sunny": "sun",
    "stella": "star", "aurora": "dawn", "orla": "gold", "goldie": "gold", "rocco": "rock",
    "petra": "rock", "silas": "tree nature", "flynn": "", "miles": "travel", "nova": "new star",
}

_SUFFIXES = ("ify", "ly", "io", "hq", "able", "ster", "hub", "labs", "ai", "base", "flow", "kit")
_PREFIXES = ("get", "try", "go", "use", "my", "join")
_COMPOUND_TAILS = (
    "box", "book", "hub", "base", "stack", "craft", "forge", "field", "path", "ware", "mind",
    "works", "bird", "fox", "lab", "nest", "yard", "well", "spring", "stone", "light", "mark",
    "line", "beam", "wave", "leaf", "point", "shift", "bloom", "chimp", "cast", "loop", "deck",
)
_COMPOUND_HEADS = ("blue", "bright", "true", "open", "deep", "clear", "north", "red", "silver", "bold", "wild", "happy")
_INVENTED_ENDINGS = ("o", "a", "i", "ia", "io", "ix", "ly", "oo", "eo", "ar", "ex", "ra", "va", "zy", "ow", "ic", "on", "er", "u")
_CLASSICAL_ENDINGS = ("a", "ia", "is", "us", "um", "on", "os", "eon", "ara", "ium", "ica", "ora", "ix")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(word: str) -> str:
    word = unicodedata.normalize("NFKD", word or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", word.lower())


def _lookup(word: str) -> Optional[str]:
    """Map a seed word to a lexicon concept, trying simple English stems."""
    candidates = [word]
    for suf in ("ies", "es", "s", "ing", "ed", "er", "ers", "ly", "y", "ity", "ness", "al", "ic", "tion"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            stem = word[: -len(suf)]
            candidates += [stem, stem + "e", stem + "y"]
    for c in candidates:
        if c in _LEX:
            return c
        if c in _ALIASES:
            return _ALIASES[c]
    return None


def _uniq(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def expand(seeds: Iterable[str], extra_concepts: Optional[dict] = None) -> Concepts:
    """Expand seed words into related English, Latin and Greek vocabulary.

    *extra_concepts* (from the optional LLM) has the same shape as
    ``Concepts.as_dict()`` and is merged in.
    """
    seed_list = _uniq(_clean(s) for s in seeds)
    con = Concepts(seeds=seed_list)
    for s in seed_list:
        key = _lookup(s)
        if not key:
            con.unknown.append(s)
            continue
        con.keys.append(key)
        syn, la, gr = _LEX[key]
        con.synonyms += syn.split()
        for w in la.split():
            con.latin.append(w)
            con.gloss.setdefault(w, f"Latin for {key}")
        for w in gr.split():
            con.greek.append(w)
            con.gloss.setdefault(w, f"Greek for {key}")
    if extra_concepts:
        con.synonyms += [_clean(w) for w in extra_concepts.get("synonyms", [])]
        for lang, bucket in (("Latin", con.latin), ("Greek", con.greek)):
            for item in extra_concepts.get(lang.lower(), []):
                w = _clean(item.get("word", "") if isinstance(item, dict) else item)
                bucket.append(w)
                if isinstance(item, dict) and item.get("meaning"):
                    con.gloss.setdefault(w, f"{lang} for {item['meaning']}")
    con.keys = _uniq(con.keys)
    con.synonyms = [w for w in _uniq(con.synonyms) if w not in seed_list]
    con.latin = _uniq(con.latin)
    con.greek = _uniq(con.greek)
    return con


_VOWELS = set("aeiouy")


def brand_score(name: str) -> int:
    """0-100 brandability: short, pronounceable, easy to spell."""
    n = _clean(name)
    if not n:
        return 0
    score = 100.0
    length = len(n)
    if length < 5:
        score -= (5 - length) * 8
    elif length > 7:
        score -= (length - 7) * 7
    vowels = sum(c in _VOWELS for c in n)
    ratio = vowels / length
    if ratio < 0.25 or ratio > 0.7:
        score -= 18
    for cluster in re.findall(r"[^aeiouy]{3,}", n):
        score -= 12 * (len(cluster) - 2)
    for run in re.findall(r"[aeiou]{3,}", n):
        score -= 10 * (len(run) - 2)
    if re.search(r"(.)\1\1", n):
        score -= 30
    if re.search(r"q(?!u)", n):
        score -= 8
    if not re.fullmatch(r"(?:[^aeiouy]{0,2}[aeiouy]{1,2})+[^aeiouy]{0,2}", n):
        score -= 6  # awkward consonant/vowel rhythm
    return max(0, min(100, int(round(score))))


def _onset(word: str) -> str:
    """First syllable-ish chunk: consonants + vowel group + one consonant."""
    m = re.match(r"[^aeiouy]*[aeiouy]+[^aeiouy]?", word)
    return m.group(0) if m else word[:3]


def _stem(word: str) -> str:
    """Strip a Latin/Greek inflection so a new ending can be attached."""
    for end in ("ium", "ius", "us", "um", "os", "on", "is", "es", "ia", "a", "e", "o", "i"):
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)]
    return word


# ---------------------------------------------------------------------------
# Vibe generators: each yields Idea objects (unranked, may contain dupes).
# ---------------------------------------------------------------------------

def _gen_human(con: Concepts, rng: random.Random) -> list[Idea]:
    roots = con.seeds + con.synonyms[:10]
    scored: list[tuple[float, str, str]] = []
    for name, tags in _NAMES.items():
        why = ""
        s = max((jaro_winkler_similarity(name, r) for r in roots), default=0.0)
        if any(name[0] == r[0] for r in con.seeds):
            s += 0.15
        hit = set(tags.split()) & set(con.keys)
        if hit:
            s += 0.6
            why = f"evokes {', '.join(sorted(hit))}"
        s += rng.random() * 0.15
        scored.append((s, name, why))
    scored.sort(reverse=True)
    out: list[Idea] = []
    for _s, name, why in scored[:10]:
        base = why or "friendly human name"
        out.append(Idea(name, "human", base))
        out.append(Idea("hey" + name, "human", f"'Hey {name.title()}' - {base}"))
        out.append(Idea("meet" + name, "human", f"'Meet {name.title()}' - {base}"))
        out.append(Idea(name + "hq", "human", base))
    return out


def _gen_invented(con: Concepts, rng: random.Random) -> list[Idea]:
    roots = _uniq(con.seeds + con.latin + con.greek + con.synonyms[:8])
    onsets = _uniq(_onset(r) for r in roots if len(r) >= 3)
    out: list[Idea] = []
    for o in onsets:
        src = next((r for r in roots if r.startswith(o)), o)
        for end in rng.sample(_INVENTED_ENDINGS, k=min(7, len(_INVENTED_ENDINGS))):
            core = o[:-1] if (o[-1] in _VOWELS and end[0] in _VOWELS) else o
            out.append(Idea(core + end, "invented", f"coined from '{src}'"))
    for a in onsets:
        for b in rng.sample(onsets, k=min(4, len(onsets))):
            if a == b:
                continue
            tail = _stem(b) if len(b) > 3 else b
            blend = a + tail[-2:] + rng.choice(("a", "o", "i", "ia", "er"))
            out.append(Idea(blend, "invented", f"blend of '{a}' + '{b}'"))
    for r in roots[:6]:  # playful reduplication: "Hulu", "Kiki"
        cv = re.match(r"[^aeiouy]*[aeiouy]", r)
        if cv and 2 <= len(cv.group(0)) <= 3:
            out.append(Idea(cv.group(0) * 2, "invented", f"playful repeat of '{r}'"))
    return out


def _gen_classical(con: Concepts, rng: random.Random) -> list[Idea]:
    out: list[Idea] = []
    for w in con.latin + con.greek:
        why = con.gloss.get(w, "classical root")
        if 3 <= len(w) <= 10:
            out.append(Idea(w, "classical", why))
        stem = _stem(w)
        for end in rng.sample(_CLASSICAL_ENDINGS, k=4):
            out.append(Idea(stem + end, "classical", why))
    words = con.latin + con.greek
    for a in words[:8]:
        for b in words[:8]:
            if a != b and len(a) <= 6 and len(b) <= 6:
                out.append(Idea(_stem(a) + b, "classical", f"{con.gloss.get(a, a)} + {con.gloss.get(b, b)}"))
    return out


def _gen_myth(con: Concepts, rng: random.Random) -> list[Idea]:
    keys = set(con.keys)
    ranked = []
    for name, (tags, why) in _MYTH.items():
        overlap = len(set(tags.split()) & keys)
        sim = max((jaro_winkler_similarity(name, s) for s in con.seeds), default=0)
        ranked.append((overlap * 2 + sim + rng.random() * 0.3, name, why))
    ranked.sort(reverse=True)
    out: list[Idea] = []
    for _s, name, why in ranked[:12]:
        out.append(Idea(name, "myth", why))
        out.append(Idea(name + "labs", "myth", why))
        out.append(Idea("get" + name, "myth", why))
    return out


def _gen_real(con: Concepts, rng: random.Random) -> list[Idea]:
    words = con.seeds + con.synonyms
    return [Idea(w, "real", "everyday word as a metaphor") for w in words if 3 <= len(w) <= 9]


def _gen_compound(con: Concepts, rng: random.Random) -> list[Idea]:
    short = [w for w in _uniq(con.seeds + con.synonyms) if 3 <= len(w) <= 6]
    out: list[Idea] = []
    for w in short:
        for tail in rng.sample(_COMPOUND_TAILS, k=6):
            if tail != w:
                out.append(Idea(w + tail, "compound", f"{w} + {tail}"))
        for head in rng.sample(_COMPOUND_HEADS, k=2):
            out.append(Idea(head + w, "compound", f"{head} + {w}"))
    for a in short[:8]:
        for b in short[:8]:
            if a != b:
                out.append(Idea(a + b, "compound", f"{a} + {b}"))
    return out


def _respell(word: str) -> set[str]:
    out = set()
    if word.endswith("er") and len(word) > 4:
        out.add(word[:-2] + "r")                     # tumbler -> tumblr
    m = re.match(r"(.*[^aeiouy])([aeiou])([^aeiouy])$", word)
    if m and len(word) > 4:
        out.add(m.group(1) + m.group(3))             # orbit -> orbt (scored down if ugly)
    if "i" in word:
        out.add(word.replace("i", "y", 1))           # lift -> lyft
    if "ck" in word:
        out.add(word.replace("ck", "k"))
    if "c" in word:
        out.add(word.replace("c", "k", 1))
    if "ph" in word:
        out.add(word.replace("ph", "f"))
    if word.endswith("s"):
        out.add(word[:-1] + "z")
    if word[-1] not in _VOWELS and len(word) <= 6:
        out.add(word + word[-1] + "r")               # fiver -> fiverr style
        out.add(word + "r")
    if word.endswith("y"):
        out.add(word[:-1] + "ee")
        out.add(word[:-1] + "i")
    out.discard(word)
    return out


def _gen_dropped(con: Concepts, rng: random.Random) -> list[Idea]:
    out: list[Idea] = []
    for w in _uniq(con.seeds + con.synonyms):
        for v in _respell(w):
            out.append(Idea(v, "dropped", f"respelling of '{w}'"))
    return out


def _gen_suffix(con: Concepts, rng: random.Random) -> list[Idea]:
    out: list[Idea] = []
    for w in _uniq(con.seeds + con.synonyms[:6]):
        if len(w) > 8:
            continue
        for suf in _SUFFIXES:
            joined = (w[:-1] if w[-1] in "aeiouy" and suf[0] in "aeiouy" else w) + suf
            out.append(Idea(joined, "suffix", f"{w} + -{suf}"))
        for pre in _PREFIXES:
            out.append(Idea(pre + w, "suffix", f"{pre}- + {w}"))
    return out


_GENERATORS = {
    "human": _gen_human, "invented": _gen_invented, "classical": _gen_classical,
    "myth": _gen_myth, "real": _gen_real, "compound": _gen_compound,
    "dropped": _gen_dropped, "suffix": _gen_suffix,
}


def ideas_for(
    con: Concepts,
    vibes: Iterable[str],
    per_vibe: int = 20,
    salt: int = 0,
) -> list[Idea]:
    """Top *per_vibe* names for each vibe, ranked by brandability with some
    randomness so repeated runs surface different ideas."""
    rng = random.Random(f"{salt}|{','.join(con.seeds)}")
    seen: set[str] = set()
    out: list[Idea] = []
    for vibe in vibes:
        gen = _GENERATORS.get(vibe)
        if not gen:
            continue
        pool: dict[str, Idea] = {}
        for idea in gen(con, rng):
            n = _clean(idea.name)
            if 3 <= len(n) <= 14 and n not in seen:
                pool.setdefault(n, Idea(n, idea.vibe, idea.why))
        ranked = sorted(
            pool.values(),
            key=lambda i: brand_score(i.name) + rng.random() * 12,
            reverse=True,
        )
        for idea in ranked[:per_vibe]:
            seen.add(idea.name)
            out.append(idea)
    return out
