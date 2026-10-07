"""
One Piece TCG Pre-Order / Buy-Later Scanner

Install:
    pip install feedparser vaderSentiment

Examples:
    python onepiece_tcg_scanner.py
    python onepiece_tcg_scanner.py --list
    python onepiece_tcg_scanner.py OP-18 --price 110 --target 115
    python onepiece_tcg_scanner.py EB-05 --price 100 --target 110
    python onepiece_tcg_scanner.py OP-18 EB-05
    python onepiece_tcg_scanner.py --all

IMPORTANT:
This is a research/decision-support tool, NOT financial advice.

The scanner does NOT automatically know the actual price of a box.
You enter the current pre-order price and optionally your maximum target
price.

The built-in set calendar should be updated whenever Bandai announces
new products or changes release dates.
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from urllib.parse import quote

import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


# ============================================================================
# SENTIMENT ENGINE
# ============================================================================  

analyzer = SentimentIntensityAnalyzer()


# ============================================================================
# SETTINGS
# ============================================================================

DEFAULT_CURRENCY = "USD"

# Overall score:
#
# 65+  = PRE-ORDER
# 40-64 = NEUTRAL
# <40  = WAIT

PREORDER_THRESHOLD = 65
WAIT_THRESHOLD = 40

# Minimum number of directional news signals before trusting news momentum.
MIN_NEWS_SIGNALS = 4


# ============================================================================
# WEIGHTS
# ============================================================================
#
# Total = 100
#
# RELEASE  = How good the current timing is
# DEMAND   = Character/player/collector/competitive demand
# CHASE    = Strength of chase cards
# SUPPLY   = Scarcity/allocation/supply situation
# REPRINT  = Risk of reprints/restocks
# NEWS     = Current market/news momentum
# PRICE    = How attractive your entered pre-order price is
#

WEIGHTS = {
    "release": 10,
    "demand": 20,
    "chase": 20,
    "supply": 15,
    "reprint": 15,
    "news": 10,
    "price": 10,
}


# ============================================================================
# ONE PIECE PRODUCT DATABASE
# ============================================================================
#
# You can add future sets here.
#
# demand:
#   1 = very weak
#   2 = weak
#   3 = average
#   4 = strong
#   5 = extremely strong
#
# chase:
#   1 = weak chase cards
#   5 = extremely strong chase potential
#
# supply:
#   1 = abundant supply
#   5 = potentially scarce
#
# reprint:
#   1 = high reprint risk
#   5 = low reprint risk
#

PRODUCTS = {

    "EB-05": {
        "name": "Extra Booster: One Piece Heroines Edition Vol. 2",
        "type": "Extra Booster",
        "release": "2026-10-30",

        "keywords": [
            "One Piece EB-05",
            "One Piece EB05",
            "One Piece Heroines Edition Vol 2",
            "One Piece Heroines Vol 2",
        ],

        "demand": 4,
        "chase": 4,
        "supply": 3,
        "reprint": 3,

        "notes":
            "Heroine-focused extra booster. "
            "Character popularity and chase-card reveals are important."
    },


    "OP-18": {
        "name": "The Dominance of God",
        "type": "Booster",
        "release": "2026-11-20",

        "keywords": [
            "One Piece OP-18",
            "One Piece OP18",
            "One Piece The Dominance of God",
            "One Piece OP 18",
        ],

        "demand": 4,
        "chase": 4,
        "supply": 3,
        "reprint": 3,

        "notes":
            "Upcoming main booster. "
            "Update demand/chase values as the card list is revealed."
    },


    "OP-17": {
        "name": "The World's Strongest Warriors",
        "type": "Booster",
        "release": "2026-08-28",

        "keywords": [
            "One Piece OP-17",
            "One Piece OP17",
            "One Piece World's Strongest Warriors",
        ],

        "demand": 5,
        "chase": 5,
        "supply": 3,
        "reprint": 3,

        "notes":
            "Released set. Useful as a historical benchmark."
    },


    "OP-16": {
        "name": "The Time of Battle",
        "type": "Booster",
        "release": "2026-06-12",

        "keywords": [
            "One Piece OP-16",
            "One Piece OP16",
            "One Piece The Time of Battle",
        ],

        "demand": 4,
        "chase": 4,
        "supply": 3,
        "reprint": 3,

        "notes":
            "Released set. Useful for historical comparison."
    },


    "OP-15": {
        "name": "Adventure on Kami's Island",
        "type": "Booster",
        "release": "2026-04-03",

        "keywords": [
            "One Piece OP-15",
            "One Piece OP15",
            "One Piece Adventure on Kami's Island",
        ],

        "demand": 4,
        "chase": 4,
        "supply": 3,
        "reprint": 3,

        "notes":
            "Released set. Useful for historical comparison."
    },


    "OP-14": {
        "name": "The Azure Sea's Seven",
        "type": "Booster",
        "release": "2026-01-16",

        "keywords": [
            "One Piece OP-14",
            "One Piece OP14",
            "One Piece Azure Sea's Seven",
        ],

        "demand": 4,
        "chase": 4,
        "supply": 3,
        "reprint": 3,

        "notes":
            "Released set. Useful for historical comparison."
    },

}


# ============================================================================
# HEADLINE KEYWORDS
# ============================================================================

RISING = re.compile(
    r"\b("
    r"ris\w*|"
    r"surge\w*|"
    r"jump\w*|"
    r"increas\w*|"
    r"climb\w*|"
    r"soar\w*|"
    r"spik\w*|"
    r"higher|"
    r"rall\w*|"
    r"shortage\w*|"
    r"scarce\w*|"
    r"tighten\w*|"
    r"premium\w*|"
    r"demand\w*|"
    r"sold\s*out|"
    r"sell\s*out|"
    r"expensive|"
    r"record\s*high"
    r")\b",
    re.I,
)


FALLING = re.compile(
    r"\b("
    r"drop\w*|"
    r"fall\w*|"
    r"fell|"
    r"declin\w*|"
    r"slump\w*|"
    r"plung\w*|"
    r"lower|"
    r"decreas\w*|"
    r"tumble\w*|"
    r"dip\w*|"
    r"sink\w*|"
    r"slid\w*|"
    r"rollback\w*|"
    r"oversupply|"
    r"glut|"
    r"weaken\w*|"
    r"cheaper|"
    r"discount\w*|"
    r"reprint\w*|"
    r"restock\w*|"
    r"overprinted|"
    r"supply\s*increase"
    r")\b",
    re.I,
)


REPRINT_WORDS = re.compile(
    r"\b("
    r"reprint\w*|"
    r"restock\w*|"
    r"reissued|"
    r"additional\s*printing|"
    r"print\s*run|"
    r"mass\s*print\w*"
    r")\b",
    re.I,
)


CHASE_WORDS = re.compile(
    r"\b("
    r"manga|"
    r"manga\s*rare|"
    r"god\s*rare|"
    r"sp|"
    r"alternate\s*art|"
    r"alt\s*art|"
    r"leader|"
    r"parallel|"
    r"chase|"
    r"case\s*hit|"
    r"top\s*card|"
    r"signature|"
    r"rare\s*card|"
    r"wanted"
    r")\b",
    re.I,
)


DEMAND_WORDS = re.compile(
    r"\b("
    r"hype|"
    r"demand|"
    r"popular|"
    r"popular\w*|"
    r"competitive|"
    r"meta|"
    r"tournament|"
    r"staple|"
    r"collector|"
    r"collectors|"
    r"iconic|"
    r"luffy|"
    r"shanks|"
    r"zoro|"
    r"nami|"
    r"boa|"
    r"robin|"
    r"ace|"
    r"law|"
    r"gear\s*5"
    r")\b",
    re.I,
)


SUPPLY_WORDS = re.compile(
    r"\b("
    r"shortage|"
    r"scarce|"
    r"allocation|"
    r"allocated|"
    r"limited|"
    r"low\s*supply|"
    r"sold\s*out|"
    r"restock|"
    r"supply|"
    r"print\s*run|"
    r"printing|"
    r"available"
    r")\b",
    re.I,
)


# ============================================================================
# OUTPUT STORAGE
# ============================================================================

LINES = []
RESULTS = []


def log(line=""):
    """
    Print to terminal and save for report.
    """

    print(line)
    LINES.append(line)


# ============================================================================
# DATE FUNCTIONS
# ============================================================================

def parse_date(value):
    return date.fromisoformat(value)


def days_until(release):
    return (parse_date(release) - date.today()).days


# ============================================================================
# NEWS
# ============================================================================

def fetch_news(query, num_articles=10):
    """
    Search Google News RSS.
    """

    rss_url = f"https://news.google.com/rss/search?q={quote(query)}"

    try:
        feed = feedparser.parse(rss_url)
    except Exception:
        return []

    articles = []

    for item in feed.entries[:num_articles]:

        articles.append(
            {
                "title": getattr(item, "title", ""),
                "link": getattr(item, "link", ""),
                "published": item.get("published", "n/a"),
            }
        )

    return articles


def analyze_sentiment(text):
    """
    VADER sentiment score from -1 to +1.
    """

    return analyzer.polarity_scores(text)["compound"]


def price_direction(title):
    """
    +1 = rising
    -1 = falling
     0 = unclear
    """

    rising = len(RISING.findall(title))
    falling = len(FALLING.findall(title))

    if rising > falling:
        return 1

    if falling > rising:
        return -1

    return 0


# ============================================================================
# NEWS RESULT
# ============================================================================

@dataclass
class NewsResult:

    articles: list

    rising: int
    falling: int
    unclear: int

    sentiment: float

    reprint_hits: int
    chase_hits: int
    demand_hits: int
    supply_hits: int


# ============================================================================
# SCAN NEWS
# ============================================================================

def scan_news(product, articles_per_query=8):

    seen = set()
    articles = []

    for query in product["keywords"]:

        log(f"Fetching: {query}")

        found = fetch_news(
            query,
            articles_per_query
        )

        for article in found:

            key = article["title"].strip().lower()

            if key and key not in seen:

                seen.add(key)

                articles.append(article)

    rising = 0
    falling = 0
    unclear = 0

    sentiment_total = 0.0

    reprint_hits = 0
    chase_hits = 0
    demand_hits = 0
    supply_hits = 0

    for article in articles:

        title = article["title"]

        sentiment_total += analyze_sentiment(title)

        direction = price_direction(title)

        if direction > 0:
            rising += 1

        elif direction < 0:
            falling += 1

        else:
            unclear += 1

        reprint_hits += len(
            REPRINT_WORDS.findall(title)
        )

        chase_hits += len(
            CHASE_WORDS.findall(title)
        )

        demand_hits += len(
            DEMAND_WORDS.findall(title)
        )

        supply_hits += len(
            SUPPLY_WORDS.findall(title)
        )

    if articles:

        avg_sentiment = (
            sentiment_total / len(articles)
        )

    else:

        avg_sentiment = 0.0

    return NewsResult(

        articles=articles,

        rising=rising,
        falling=falling,
        unclear=unclear,

        sentiment=avg_sentiment,

        reprint_hits=reprint_hits,
        chase_hits=chase_hits,
        demand_hits=demand_hits,
        supply_hits=supply_hits,
    )


# ============================================================================
# SCORE HELPERS
# ============================================================================

def clamp(
    value,
    low=0.0,
    high=100.0
):

    return max(
        low,
        min(high, value)
    )


# ============================================================================
# RELEASE TIMING SCORE
# ============================================================================

def score_release(product):

    """
    Best pre-order window is roughly 2-8 weeks before release.
    """

    days = days_until(
        product["release"]
    )

    # Already released
    if days < 0:
        return 10.0

    # Less than one week
    if days <= 7:
        return 55.0

    # 1-2 weeks
    if days <= 14:
        return 75.0

    # 2-8 weeks
    if days <= 56:
        return 100.0

    # 2-3 months
    if days <= 90:
        return 75.0

    # Too early
    return 50.0


# ============================================================================
# NEWS SCORE
# ============================================================================

def score_news(news):

    directional = (
        news.rising +
        news.falling
    )

    if directional < MIN_NEWS_SIGNALS:

        return 50.0

    momentum = (
        news.rising -
        news.falling
    ) / directional

    return clamp(
        50 +
        momentum * 50
    )


# ============================================================================
# DEMAND SCORE
# ============================================================================

def score_demand(
    product,
    news
):

    base = (
        product["demand"] *
        20.0
    )

    boost = min(
        news.demand_hits * 2.0,
        15.0
    )

    return clamp(
        base + boost
    )


# ============================================================================
# CHASE SCORE
# ============================================================================

def score_chase(
    product,
    news
):

    base = (
        product["chase"] *
        20.0
    )

    boost = min(
        news.chase_hits * 2.0,
        15.0
    )

    return clamp(
        base + boost
    )


# ============================================================================
# SUPPLY SCORE
# ============================================================================

def score_supply(
    product,
    news
):

    base = (
        product["supply"] *
        20.0
    )

    scarcity = 0

    for article in news.articles:

        title = article["title"].lower()

        scarcity_words = (
            "shortage",
            "scarce",
            "allocation",
            "allocated",
            "sold out",
            "limited supply",
            "low supply",
        )

        if any(
            word in title
            for word in scarcity_words
        ):

            scarcity += 1

    scarcity_boost = min(
        scarcity * 3.0,
        15.0
    )

    oversupply_penalty = min(
        news.reprint_hits * 2.0,
        20.0
    )

    return clamp(
        base +
        scarcity_boost -
        oversupply_penalty
    )


# ============================================================================
# REPRINT SCORE
# ============================================================================

def score_reprint(
    product,
    news
):

    """
    Higher score =
    lower reprint risk =
    better for pre-order.
    """

    base = (
        product["reprint"] *
        20.0
    )

    penalty = min(
        news.reprint_hits * 4.0,
        35.0
    )

    return clamp(
        base - penalty
    )


# ============================================================================
# PRICE SCORE
# ============================================================================

def score_price(
    current_price,
    target_price=None
):

    """
    If the user supplies a target price:

        current <= 85% target = excellent
        current <= 95% target = very good
        current <= 100% target = good
        current <= 110% target = neutral
        current <= 120% target = poor
        >120% target          = very poor

    """

    if (
        current_price is None
        or target_price is None
    ):

        return 50.0

    if target_price <= 0:

        return 50.0

    ratio = (
        current_price /
        target_price
    )

    if ratio <= 0.85:
        return 100.0

    if ratio <= 0.95:
        return 85.0

    if ratio <= 1.00:
        return 75.0

    if ratio <= 1.10:
        return 50.0

    if ratio <= 1.20:
        return 30.0

    return 10.0


# ============================================================================
# OVERALL SCORE
# ============================================================================

def calculate_score(
    product,
    news,
    current_price=None,
    target_price=None
):

    components = {

        "release":
            score_release(product),

        "demand":
            score_demand(
                product,
                news
            ),

        "chase":
            score_chase(
                product,
                news
            ),

        "supply":
            score_supply(
                product,
                news
            ),

        "reprint":
            score_reprint(
                product,
                news
            ),

        "news":
            score_news(news),

        "price":
            score_price(
                current_price,
                target_price
            ),
    }

    total = 0.0

    for key in components:

        total += (
            components[key] *
            WEIGHTS[key] /
            100.0
        )

    return clamp(
        total
    ), components


# ============================================================================
# VERDICT
# ============================================================================

def verdict(
    score,
    product,
    current_price=None,
    target_price=None
):

    days = days_until(
        product["release"]
    )

    if days < 0:

        return (
            "RELEASED",
            "This product has already passed "
            "its scheduled release date."
        )

    if score >= PREORDER_THRESHOLD:

        if current_price is None:

            return (
                "PRE-ORDER",
                "The overall signals favour securing "
                "product before release. Enter the "
                "actual pre-order price before making "
                "a price-specific decision."
            )

        return (
            "PRE-ORDER",
            "The combined timing, demand, chase, "
            "supply, reprint and market signals favour "
            "locking in the current pre-order price."
        )

    if score <= WAIT_THRESHOLD:

        return (
            "WAIT",
            "The current evidence does not justify "
            "locking up cash this early. Watch price, "
            "card reveals, supply and release-week "
            "listings."
        )

    return (
        "NEUTRAL",
        "Signals are mixed. Avoid a large commitment "
        "until more cards and real market prices "
        "are available."
    )


# ============================================================================
# PRINT NEWS
# ============================================================================

def print_news_details(
    news,
    limit=12
):

    if not news.articles:

        log(
            "No news articles found."
        )

        return

    direction_names = {

        1: "Rising",
        -1: "Falling",
        0: "Unclear",
    }

    log(
        "\n--- News sample ---"
    )

    for index, article in enumerate(
        news.articles[:limit],
        1
    ):

        direction = price_direction(
            article["title"]
        )

        log(
            f"{index}. "
            f"{article['title']}"
        )

        log(
            f"   {article['published']}"
        )

        log(
            "   Direction: "
            f"{direction_names[direction]}"
        )

        if article["link"]:

            log(
                f"   {article['link']}"
            )


# ============================================================================
# SCAN ONE PRODUCT
# ============================================================================

def scan_product(
    code,
    current_price=None,
    target_price=None,
    currency="USD",
    show_news=True
):

    code = code.upper()

    if code not in PRODUCTS:

        log(
            f"Unknown product '{code}'."
        )

        log(
            "Available: "
            + ", ".join(PRODUCTS)
        )

        return None

    product = PRODUCTS[code]

    log(
        "\n"
        + "=" * 72
    )

    log(
        f"{code} — {product['name']}"
    )

    log(
        "=" * 72
    )

    log(
        f"Type: {product['type']}"
    )

    log(
        f"English release: "
        f"{product['release']}"
    )

    log(
        f"Days until release: "
        f"{days_until(product['release'])}"
    )

    log(
        f"Notes: {product['notes']}"
    )

    if current_price is not None:

        log(
            f"Your pre-order price: "
            f"{currency.upper()} "
            f"{current_price:.2f}"
        )

    else:

        log(
            "Your pre-order price: not supplied"
        )

    if target_price is not None:

        log(
            f"Your target/max price: "
            f"{currency.upper()} "
            f"{target_price:.2f}"
        )

    # ------------------------------------------------------------------------
    # NEWS
    # ------------------------------------------------------------------------

    news = scan_news(
        product
    )

    # ------------------------------------------------------------------------
    # SCORE
    # ------------------------------------------------------------------------

    score, components = calculate_score(
        product,
        news,
        current_price=current_price,
        target_price=target_price,
    )

    # ------------------------------------------------------------------------
    # VERDICT
    # ------------------------------------------------------------------------

    action, explanation = verdict(
        score,
        product,
        current_price=current_price,
        target_price=target_price,
    )

    # ------------------------------------------------------------------------
    # BREAKDOWN
    # ------------------------------------------------------------------------

    log(
        "\n--- Signal breakdown ---"
    )

    for key, value in components.items():

        log(
            f"{key.title():10s}: "
            f"{value:6.1f}/100  "
            f"weight={WEIGHTS[key]}%"
        )

    # ------------------------------------------------------------------------
    # NEWS SUMMARY
    # ------------------------------------------------------------------------

    log(
        f"\nOverall score: "
        f"{score:.1f}/100"
    )

    log(
        f"News articles: "
        f"{len(news.articles)}"
    )

    log(
        f"Rising-price headlines: "
        f"{news.rising}"
    )

    log(
        f"Falling-price headlines: "
        f"{news.falling}"
    )

    log(
        f"Unclear headlines: "
        f"{news.unclear}"
    )

    log(
        f"Average headline sentiment: "
        f"{news.sentiment:+.2f}"
    )

    # ------------------------------------------------------------------------
    # VERDICT
    # ------------------------------------------------------------------------

    log(
        f"\nVERDICT: {action}"
    )

    log(
        f"Why: {explanation}"
    )

    # ------------------------------------------------------------------------
    # NEWS
    # ------------------------------------------------------------------------

    if show_news:

        print_news_details(
            news
        )

    # ------------------------------------------------------------------------
    # SAVE RESULT FOR CSV
    # ------------------------------------------------------------------------

    result = {

        "code":
            code,

        "name":
            product["name"],

        "type":
            product["type"],

        "release":
            product["release"],

        "days_until":
            days_until(
                product["release"]
            ),

        "current_price":
            current_price
            if current_price is not None
            else "",

        "target_price":
            target_price
            if target_price is not None
            else "",

        "score":
            round(
                score,
                2
            ),

        "verdict":
            action,

        "news_articles":
            len(news.articles),

        "rising":
            news.rising,

        "falling":
            news.falling,

        "reprint_hits":
            news.reprint_hits,

        "demand_hits":
            news.demand_hits,

        "chase_hits":
            news.chase_hits,

        "supply_hits":
            news.supply_hits,
    }

    RESULTS.append(
        result
    )

    return result


# ============================================================================
# SAVE REPORTS
# ============================================================================

def save_results():

    try:

        folder = Path(
            __file__
        ).resolve().parent

    except NameError:

        folder = Path.cwd()

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H%M%S"
    )

    # ------------------------------------------------------------------------
    # TXT
    # ------------------------------------------------------------------------

    txt_path = (
        folder /
        f"onepiece_tcg_scan_{timestamp}.txt"
    )

    txt_path.write_text(
        "\n".join(LINES),
        encoding="utf-8"
    )

    # ------------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------------

    csv_path = (
        folder /
        f"onepiece_tcg_scan_{timestamp}.csv"
    )

    if RESULTS:

        with csv_path.open(
            "w",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=RESULTS[0].keys()
            )

            writer.writeheader()

            writer.writerows(
                RESULTS
            )

    print(
        f"\nText report saved to: "
        f"{txt_path}"
    )

    if RESULTS:

        print(
            f"CSV report saved to: "
            f"{csv_path}"
        )


# ============================================================================
# LIST PRODUCTS
# ============================================================================

def list_products():

    log(
        "\nAvailable One Piece TCG products:"
    )

    log(
        "-" * 90
    )

    for code, product in sorted(
        PRODUCTS.items()
    ):

        days = days_until(
            product["release"]
        )

        if days >= 0:

            status = "UPCOMING"

        else:

            status = "RELEASED"

        log(
            f"{code:8s} | "
            f"{product['release']} | "
            f"{status:9s} | "
            f"{product['name']}"
        )


# ============================================================================
# COMMAND LINE
# ============================================================================

def build_parser():

    parser = argparse.ArgumentParser(

        description=(
            "One Piece TCG "
            "pre-order / buy-later scanner"
        )
    )

    parser.add_argument(

        "products",

        nargs="*",

        help=(
            "Set codes, e.g. "
            "EB-05 OP-18. "
            "Omit to scan upcoming products."
        ),
    )

    parser.add_argument(

        "--all",

        action="store_true",

        help=(
            "Scan all products "
            "in the database."
        ),
    )

    parser.add_argument(

        "--list",

        action="store_true",

        help=(
            "List available products "
            "and exit."
        ),
    )

    parser.add_argument(

        "--price",

        type=float,

        default=None,

        help=(
            "Current pre-order price "
            "for a selected product."
        ),
    )

    parser.add_argument(

        "--target",

        type=float,

        default=None,

        help=(
            "Your maximum/target "
            "pre-order price."
        ),
    )

    parser.add_argument(

        "--currency",

        default=DEFAULT_CURRENCY,

        help=(
            "Currency label, "
            "e.g. USD, PHP, SGD."
        ),
    )

    parser.add_argument(

        "--no-news",

        action="store_true",

        help=(
            "Skip individual "
            "headline output."
        ),
    )

    return parser


# ============================================================================
# MAIN
# ============================================================================

def main():

    parser = build_parser()

    args = parser.parse_args()

    # ------------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------------

    if args.price is not None:

        if args.price < 0:

            parser.error(
                "--price cannot be negative"
            )

    if args.target is not None:

        if args.target <= 0:

            parser.error(
                "--target must be greater than zero"
            )

    # ------------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------------

    if args.list:

        list_products()

        return

    # ------------------------------------------------------------------------
    # SELECT PRODUCTS
    # ------------------------------------------------------------------------

    selected = [
        product.upper()
        for product in args.products
    ]

    if args.all:

        selected = list(
            PRODUCTS.keys()
        )

    # Default = upcoming products
    if not selected:

        selected = [

            code

            for code, product
            in PRODUCTS.items()

            if days_until(
                product["release"]
            ) >= 0
        ]

    # ------------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------------

    log(
        "One Piece TCG scan started: "
        f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    )

    log(
        f"Currency label: "
        f"{args.currency.upper()}"
    )

    log(
        "Method: weighted heuristic using "
        "release timing, demand, chase strength, "
        "supply, reprint risk, news momentum and price."
    )

    # ------------------------------------------------------------------------
    # SCAN
    # ------------------------------------------------------------------------

    for code in selected:

        # Only apply --price / --target when scanning
        # exactly one product.
        #
        # This prevents accidentally treating the same
        # price as the price for every set.

        if len(selected) == 1:

            price = args.price

            target = args.target

        else:

            price = None

            target = None

        scan_product(

            code,

            current_price=price,

            target_price=target,

            currency=args.currency,

            show_news=not args.no_news,
        )

    # ------------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------------

    if RESULTS:

        log(
            "\n"
            + "=" * 72
        )

        log(
            "SUMMARY"
        )

        log(
            "=" * 72
        )

        sorted_results = sorted(

            RESULTS,

            key=lambda item:
                item["score"],

            reverse=True,
        )

        for result in sorted_results:

            log(

                f"{result['code']:8s} "
                f"{result['score']:5.1f}/100 "
                f"{result['verdict']:10s} "
                f"{result['name']}"

            )

    # ------------------------------------------------------------------------
    # DISCLAIMER
    # ------------------------------------------------------------------------

    log(
        "\nIMPORTANT:"
    )

    log(
        "This is a heuristic research tool, "
        "not financial advice."
    )

    log(
        "Headline sentiment is not a substitute "
        "for actual sold prices, local supply, "
        "retailer reliability, card reveals, "
        "or your own risk limits."
    )

    # ------------------------------------------------------------------------
    # SAVE
    # ------------------------------------------------------------------------

    save_results()


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":

    main()