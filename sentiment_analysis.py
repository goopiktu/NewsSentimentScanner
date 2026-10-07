import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# The verdict always compares buying NOW against buying LATER:
#   prices expected to rise -> buying now is cheaper than later -> GOOD
#   prices expected to fall -> waiting is cheaper than buying now -> BAD
#
# MODE only changes the wording of the suggested action:
#   "investor"  -> you buy to profit from price moves
#   "logistics" -> you buy fuel to run operations and must buy anyway,
#                  so the question is how much to buy now vs later
MODE = "logistics"

ACTIONS = {
    "investor": {
        "GOOD": "Favourable entry. Price is likely to be higher later, so consider buying now.",
        "BAD": "Unfavourable entry. Price is likely to be lower later, so wait or avoid buying now.",
        "NEUTRAL": "No clear edge. Hold off or keep position sizes small.",
    },
    "logistics": {
        "GOOD": "Buy ahead: stock up, fill tanks, or lock in a supply contract before prices rise.",
        "BAD": "Buy only what operations need now and delay any extra or stockpile purchases.",
        "NEUTRAL": "Carry on with normal purchasing. No timing advantage either way.",
    },
}

if MODE not in ACTIONS:
    raise ValueError(f"MODE must be one of: {', '.join(ACTIONS)}")

# Net score needed (range -1 to +1) before calling it good or bad
THRESHOLD = 0.2

# Minimum number of headlines that mention a price direction before the
# verdict is trusted. Below this, the result is reported as inconclusive.
MIN_SIGNALS = 5

RUNS = {
    "diesel": [
        "diesel Philippines",
        "diesel price Philippines",
        "diesel Philippines forecast",
        "diesel Philippines supply",
        "diesel price hike Philippines",
        "diesel price rollback Philippines",
        "diesel price adjustment next week",
        "Philippines fuel prices DOE",
        "Philippines oil companies price adjustment",
        "Philippines pump price diesel",
        "Philippines oil price outlook",
        "Brent crude oil price",
    ],
    "ifo180": [
        "IFO 180 bunker fuel",
        "IFO 180 price",
        "IFO 180 bunker market",
        "IFO 180 forecast",
        "IFO 180 Singapore bunker",
        "bunker fuel prices Asia",
        "bunker prices Singapore",
        "HSFO price",
        "high sulfur fuel oil price",
        "marine fuel price outlook",
        "fuel oil 380 price",
        "Brent crude oil price",
    ],
}

# Headline keywords that signal the direction of PRICES
RISING = re.compile(
    r"\b(ris(e|es|ing)|rose|hik(e|es|ed|ing)|surg\w*|jump\w*|increas\w*|"
    r"climb\w*|soar\w*|spik\w*|higher|rall(y|ies|ied)|shortage\w*|"
    r"tighten\w*|upsurge)\b",
    re.I,
)
FALLING = re.compile(
    r"\b(drop\w*|fall\w*|fell|declin\w*|slump\w*|plung\w*|lower\w*|"
    r"eas(e|es|ed|ing)|decreas\w*|tumbl\w*|dip\w*|sink\w*|slid\w*|"
    r"rollback\w*|roll\s?back|price\s+cut\w*|slash\w*|oversupply|glut|"
    r"weaken\w*|cheaper)\b",
    re.I,
)

LINES = []


def log(line=""):
    """Print to the screen and keep a copy for the text file."""
    print(line)
    LINES.append(line)


def fetch_news(query, num_articles=10):
    rss_url = f"https://news.google.com/rss/search?q={quote(query)}"
    feed = feedparser.parse(rss_url)
    return [
        {
            "title": item.title,
            "link": item.link,
            "published": item.get("published", "n/a"),
        }
        for item in feed.entries[:num_articles]
    ]


def analyze_sentiment(text):
    polarity = analyzer.polarity_scores(text)["compound"]
    if polarity > 0.05:
        return polarity, "Positive"
    if polarity < -0.05:
        return polarity, "Negative"
    return polarity, "Neutral"


def price_direction(title):
    """Return +1 if the headline points to rising prices, -1 for falling, 0 if unclear."""
    rising = len(RISING.findall(title))
    falling = len(FALLING.findall(title))
    if rising > falling:
        return 1
    if falling > rising:
        return -1
    return 0


def buy_verdict(rising_count, falling_count):
    """
    Compare buying NOW with buying LATER.
    Rising-price headlines  -> buying now beats buying later (GOOD).
    Falling-price headlines -> waiting beats buying now (BAD).
    Returns (verdict, net_score, outlook, suggested_action).
    """
    directional = rising_count + falling_count
    if directional < MIN_SIGNALS:
        outlook = (
            f"Only {directional} headline(s) mention a price direction "
            f"(need {MIN_SIGNALS}). Not enough evidence."
        )
        return "NEUTRAL", 0.0, outlook, ACTIONS[MODE]["NEUTRAL"]

    net = (rising_count - falling_count) / directional

    if net >= THRESHOLD:
        verdict = "GOOD"
        outlook = "Prices are expected to rise, so buying now beats buying later."
    elif net <= -THRESHOLD:
        verdict = "BAD"
        outlook = "Prices are expected to fall, so waiting beats buying now."
    else:
        verdict = "NEUTRAL"
        outlook = "No clear trend. Rising and falling headlines are balanced."

    return verdict, net, outlook, ACTIONS[MODE][verdict]


def run_scan(name, queries, num_articles_per_query=10):
    log(f"\n{'=' * 60}\nRUN: {name}\n{'=' * 60}")

    # Collect articles, skipping duplicates across overlapping queries
    seen_titles = set()
    articles = []
    for query in queries:
        log(f"Fetching news for '{query}'...")
        for article in fetch_news(query, num_articles_per_query):
            if article["title"] not in seen_titles:
                seen_titles.add(article["title"])
                articles.append(article)

    if not articles:
        log("No articles found.")
        return None

    sentiment_summary = {"Positive": 0, "Negative": 0, "Neutral": 0}
    rising_count = 0
    falling_count = 0
    direction_labels = {1: "Rising", -1: "Falling", 0: "Unclear"}

    for idx, article in enumerate(articles, 1):
        polarity, sentiment = analyze_sentiment(article["title"])
        direction = price_direction(article["title"])
        sentiment_summary[sentiment] += 1
        if direction == 1:
            rising_count += 1
        elif direction == -1:
            falling_count += 1

        log(f"\nArticle {idx}: {article['title']}")
        log(f"Link: {article['link']}")
        log(f"Published: {article['published']}")
        log(f"Sentiment: {sentiment} (Polarity: {polarity:.2f})")
        log(f"Price direction: {direction_labels[direction]}")

    total = len(articles)
    log(f"\n--- Sentiment Summary: {name} ---")
    log(f"Total unique articles analyzed: {total}")
    for sentiment, count in sentiment_summary.items():
        log(f"{sentiment}: {count} ({count / total * 100:.2f}%)")

    verdict, net, outlook, action = buy_verdict(rising_count, falling_count)
    log(f"\n--- Buy Signal: {name} ({MODE} mode) ---")
    log(f"Headlines pointing to rising prices:  {rising_count}")
    log(f"Headlines pointing to falling prices: {falling_count}")
    log(f"Headlines with no clear direction:    {total - rising_count - falling_count}")
    log(f"Net score: {net:+.2f}  (range -1 to +1, positive = favours buying now)")
    log(f"Price outlook: {outlook}")
    log(f"VERDICT: {verdict} time to buy now")
    log(f"Suggested action: {action}")

    return verdict


def save_results():
    try:
        folder = Path(__file__).resolve().parent
    except NameError:  # running inside a notebook
        folder = Path.cwd()

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = folder / f"scan_results_{stamp}.txt"
    path.write_text("\n".join(LINES), encoding="utf-8")
    print(f"\nResults saved to: {path}")


def main():
    # Usage: python scanner.py            -> runs both
    #        python scanner.py diesel     -> diesel only
    #        python scanner.py ifo180     -> IFO 180 only
    selected = sys.argv[1:] or list(RUNS)

    log(f"Scan started: {datetime.now():%Y-%m-%d %H:%M:%S}")
    log(f"Mode: {MODE}")

    verdicts = {}
    for name in selected:
        if name not in RUNS:
            log(f"Unknown run '{name}'. Choose from: {', '.join(RUNS)}")
            continue
        verdicts[name] = run_scan(name, RUNS[name])

    if len(verdicts) > 1:
        log(f"\n{'=' * 60}\nOVERALL\n{'=' * 60}")
        for name, verdict in verdicts.items():
            log(f"{name}: {verdict or 'no data'}")

    log("\nNote: this is a headline-based heuristic, not financial advice.")
    save_results()


if __name__ == "__main__":
    main()