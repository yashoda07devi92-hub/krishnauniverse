"""
Content pools for the long-form storytelling pipeline.

Same reasoning as modules/pools.py on the Shorts side: everything a viewer can
notice repeating lives in one place so it can be grown without touching pipeline
logic, and selection runs through modules/history.py so items are drawn WITHOUT
replacement rather than with `random.choice`.

    lesson/topic seeds   20  ->  80     (1 per episode -> ~26 weeks at 3/week)
    spoken sign-offs      5  ->  30     (1 per episode -> ~10 weeks)

Long-form only publishes 3 times a week, so these pools last far longer than the
Shorts equivalents even at a smaller size.

Run `python modules/pools.py` from the longform/ folder to print sizes and catch
duplicates.
"""

# ==========================================================================
# LESSON + TOPIC SEEDS  (80)
# ==========================================================================
# Each entry is (moral/lesson, story premise). One is drawn per episode and both
# halves are injected into the Gemini prompt.
TOPIC_POOL = [
    # --- honesty & truth (1-10) ---
    ("honesty", "a child who finds a lost wallet full of money"),
    ("telling the truth", "a shepherd boy who cried wolf one too many times"),
    ("honesty", "a woodcutter who drops his only axe into a deep river"),
    ("owning your mistakes", "a boy who breaks a window and lets another take the blame"),
    ("honesty", "a shopkeeper who is given the wrong change and could stay quiet"),
    ("truthfulness", "a girl who invents a story and watches it grow out of control"),
    ("integrity", "a farmer offered a fortune to sell milk he knows is spoiled"),
    ("admitting fault", "a young cook who ruins the village feast and must confess"),
    ("honesty", "a boy who finds the answers to tomorrow's test on the floor"),
    ("keeping your word", "a prince who gives his word to a humble farmer"),

    # --- kindness & compassion (11-22) ---
    ("kindness", "a lonely old man and the children who befriend him"),
    ("compassion", "a child who rescues a wounded sparrow in winter"),
    ("kindness to animals", "a boy who shares his only bread with a starving street dog"),
    ("gratitude", "a poor boy who shares his only meal with a stranger"),
    ("helping others", "village children who rebuild an old woman's broken bridge"),
    ("kindness returned", "a girl who helps a beggar who turns out to be a traveller king"),
    ("compassion", "a village that shelters a family driven out by a flood"),
    ("small kindnesses", "a boy who waters a dying tree every day for a year"),
    ("caring for elders", "a grandson who carries his grandmother to the temple each week"),
    ("kindness", "a blind woman and the child who describes the world to her"),
    ("generosity", "a baker who quietly leaves bread out for whoever needs it"),
    ("empathy", "a girl who befriends the child everyone else laughs at"),

    # --- hard work & perseverance (23-34) ---
    ("hard work", "a lazy rabbit who laughs at a slow but steady tortoise"),
    ("never giving up", "a young bird afraid to take its very first flight"),
    ("perseverance", "a spider who rebuilds her web every single morning"),
    ("hard work", "two brothers who inherit the same barren field"),
    ("patience with practice", "a boy who wants to play music but cannot yet"),
    ("effort over talent", "the slowest runner in the village who trains all winter"),
    ("preparation", "ants who store grain while the grasshopper sings"),
    ("persistence", "a girl who tries ninety-nine times to light a lamp in the wind"),
    ("hard work", "a potter whose first hundred pots all crack"),
    ("determination", "a boy who carries one stone a day to build a well"),
    ("small steps", "a child who learns to swim across a river one metre at a time"),
    ("never giving up", "a lame calf who learns to climb the hill with the herd"),

    # --- courage (35-44) ---
    ("courage", "a small boy who must cross a dark forest to fetch medicine"),
    ("bravery", "a girl who stands up to a bully twice her size"),
    ("courage", "a shy child who must speak in front of the whole village"),
    ("facing fear", "a boy terrified of water who must save a drowning puppy"),
    ("moral courage", "a child who refuses to join in when friends steal fruit"),
    ("bravery", "a girl who walks through a storm to warn a sleeping village"),
    ("courage", "the youngest goat who faces the bridge troll alone"),
    ("standing alone", "a boy who is the only one to tell the king the truth"),
    ("quiet bravery", "a child who sits with a frightened dog through a thunderstorm"),
    ("courage", "a young fisherman who rows out to fetch his lost brother"),

    # --- greed & contentment (45-56) ---
    ("greed", "a fisherman who catches a magical fish that grants wishes"),
    ("contentment", "a dog who loses his bone chasing a reflection"),
    ("greed", "a farmer with a goose that lays one golden egg a day"),
    ("enough is enough", "a merchant who wants one more field, and then one more"),
    ("contentment", "a city mouse and a country mouse who swap homes"),
    ("greed", "two travellers who find a bag of gold on a lonely road"),
    ("sharing", "two brothers and a single basket of mangoes"),
    ("simple joys", "a rich child who envies a poor child's kite"),
    ("greed", "a king who wishes everything he touches would turn to gold"),
    ("generosity over hoarding", "a squirrel who buries more nuts than he could ever eat"),
    ("contentment", "a peacock who wishes for the nightingale's voice"),
    ("moderation", "a boy who eats the whole harvest of sweets in one night"),

    # --- humility & wisdom (57-68) ---
    ("humility", "a proud peacock who learns the value of every creature"),
    ("wisdom over strength", "a clever mouse who frees a trapped lion"),
    ("respecting elders", "a clever grandson and his wise old grandmother"),
    ("humility", "a champion wrestler beaten by a thoughtful child"),
    ("listening", "a king who ignores every adviser until it is nearly too late"),
    ("wisdom", "three brothers asked to divide one camel fairly"),
    ("humility", "a tall tree that mocks the bending reed before the storm"),
    ("learning from anyone", "a scholar taught something vital by a shepherd"),
    ("not judging by looks", "a plain clay pot that holds the sweetest water"),
    ("patience", "a girl who plants a seed and waits through every season"),
    ("thinking before acting", "a boy who cuts the rope holding the bridge"),
    ("humility", "a rooster convinced the sun rises because he crows"),

    # --- friendship & forgiveness (69-80) ---
    ("forgiveness", "two best friends torn apart by a silly misunderstanding"),
    ("teamwork", "ants who must move a giant crumb before the rain comes"),
    ("loyalty", "a dog who waits at the station every evening for years"),
    ("forgiveness", "a brother who must choose between pride and his sister"),
    ("true friendship", "two friends tested when only one has food left"),
    ("teamwork", "four village children who cannot lift the log alone"),
    ("saying sorry", "a girl whose careless words hurt her closest friend"),
    ("trust", "a boy who must rely on a stranger to guide him home in fog"),
    ("loyalty", "an old horse the farmer is urged to abandon"),
    ("second chances", "a thief given work instead of punishment"),
    ("friendship across differences", "a cat and a mouse who agree to a truce"),
    ("letting go of anger", "a boy told to hammer a nail for every angry word"),
]

# ==========================================================================
# SPOKEN SIGN-OFFS  (30)
# ==========================================================================
# The narrator's closing line. Repeated word-for-word at the end of every
# episode, a single fixed sign-off is both a mass-production tell and a cue that
# trains returning viewers to click away.
CTA_CANDIDATES = [
    "Subscribe for a brand-new story every single day!",
    "If this story stayed with you, subscribe — there is a new one tomorrow.",
    "Subscribe and let a gentle story find you every day.",
    "There is a new story here every day. Come listen tomorrow.",
    "Stay with us — tomorrow's story is already waiting for you.",
    "If you enjoyed this one, subscribe and we will tell you another tomorrow.",
    "Subscribe, and share this story with someone small tonight.",
    "There are many more stories like this one. Subscribe so you do not miss them.",
    "Thank you for listening all the way to the end. Subscribe for the next one.",
    "Subscribe for a new story, and a new lesson, every single time.",
    "If this one made you think, subscribe — the next may too.",
    "Come back tomorrow. There is always another story worth hearing.",
    "Subscribe, and let us keep telling you stories worth remembering.",
    "That is the end of today's story. Follow along for tomorrow's.",
    "If you would like another, subscribe and we will begin again tomorrow.",
    "Subscribe for stories the whole family can listen to together.",
    "Tell someone this story tonight, and subscribe for the next one.",
    "Subscribe, and we will meet again in the next story.",
    "Every story here carries a lesson. Subscribe and collect them all.",
    "If your children enjoyed this, subscribe — there is a new one waiting.",
    "Follow along for a gentle story every time you need one.",
    "Subscribe so tomorrow's story reaches you without you having to look.",
    "Another story, another lesson, tomorrow. Subscribe and stay with us.",
    "If this warmed you even a little, subscribe for the next one.",
    "Subscribe for calm, kind stories with something worth keeping in them.",
    "There is a story here for every night of the week. Subscribe.",
    "Thank you for staying till the lesson. Subscribe for the next.",
    "Subscribe, and let a good story be the last thing you hear today.",
    "We will be here tomorrow with another one. Follow so you find it.",
    "Subscribe for stories that are gentle on the ears and good for the heart.",
]


POOLS = {
    "topics": TOPIC_POOL,
    "ctas": CTA_CANDIDATES,
}


def audit():
    """Return {pool_name: (size, [duplicates])} for every pool."""
    report = {}
    for name, pool in POOLS.items():
        seen, dupes = set(), []
        for item in pool:
            key = str(item).strip().lower()
            if key in seen:
                dupes.append(item)
            seen.add(key)
        report[name] = (len(pool), dupes)
    return report


if __name__ == "__main__":
    problems = 0
    for name, (size, dupes) in sorted(audit().items()):
        print(f"{name:<10}{size:>5} items   {'OK' if not dupes else str(len(dupes)) + ' DUPLICATE(S)'}")
        for d in dupes:
            print(f"                - {d}")
        problems += len(dupes)
    raise SystemExit(1 if problems else 0)
