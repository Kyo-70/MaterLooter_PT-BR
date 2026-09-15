"""Watch the Nexus posts tab, the Nexus bugs tab, the GitHub issues and the
Discord help-n-bug-reports forum for anything new, and print one line per new
thing. Silence means nothing changed.

    py -3 watch-board.py --once      one pass, then exit
    py -3 watch-board.py             poll every ten minutes for ever

State lives in private/watch-state.json so a restart does not replay what
was already seen. The first run seeds the state and prints only a summary.

What it sees: every comment on page one of the posts tab (a new comment
anywhere bumps its thread to page one), every row on the bugs tab with its
status, every reply inside those rows, and every issue and issue comment on
GitHub since the last pass.

Bug-row replies were the blind spot until 14 September 2026, and they cost two
real findings in one day: symplexity's log proving the gear duplication was still
live, and lsimo narrowing a crash to abyss gear crafting. Both sat inside rows
whose only outward sign was a changed timestamp, and one of the rows was marked
Fixed. The note here used to say the replies could not be fetched. They can: the
page's own loadIssueReplies posts to a widget endpoint, and curl gets it with the
headers jQuery would have sent. A row is only asked about when its timestamp
moves, so a quiet pass still costs two requests.

The Discord side needs the bot's token in DISCORD_BOT_TOKEN, in the
environment or in keys.local.env beside this script; without it the forum
is skipped and the seed line says so. It watches the active threads of the
forum: a new thread prints its title and opening post, and a reply in a
known thread prints the reply. Seth's own messages and the bot's are not
news. Archived threads are left alone.
"""
import io, json, os, re, subprocess, sys, time, html, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
STATE = os.path.join(REPO, "private", "watch-state.json")
MOD = "https://www.nexusmods.com/crimsondesert/mods/3402"
GLINT = "https://www.nexusmods.com/crimsondesert/mods/3472"
FLIGHT = "https://www.nexusmods.com/crimsondesert/mods/3488"
# (state suffix, line prefix, page). Master Looter keeps the bare "posts" and
# "bugs" state keys it has always had, so a state file written before Glint
# Spotter was added still reads and nothing is replayed. Anything from the
# second board is prefixed, because it belongs to a different piece of work and
# is meant to be handed straight over rather than acted on here.
BOARDS = [("", "", MOD), ("_glint", "glint ", GLINT), ("_flight", "flight ", FLIGHT)]
# (state suffix, line prefix, repo), matching BOARDS so one pass tags every
# line with the mod it belongs to and nothing has to be worked out from the
# text. Master Looter keeps the bare key and the bare prefix.
REPOS = [("", "", "shin2344234/master-looter"),
         ("_glint", "glint ", "shin2344234/glint-spotter"),
         ("_flight", "flight ", "shin2344234/flight-freedom")]
GH = REPOS[0][2]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"
INTERVAL = 600
KEYFILE = os.path.join(HERE, "keys.local.env")
DISCORD_GUILD = "1547304303646089296"
DISCORD_FORUM = "1547305334945615922"      # help-n-bug-reports
DISCORD_FORUM_NAME = "help-n-bug-reports"
SETH = "355497711568551947"
DISCORD_SELF = {SETH, "1547307453107150979"}   # Seth, the bot
# The same idea on the boards. Seth answers most rows himself, and his own reply
# arriving back as a finding is noise that trains you to ignore the channel.
#
# Hidden is not the same as unrecorded, and treating them as one cost something
# on 15 September 2026: with his replies discarded there was no way to tell a
# thread nobody had answered from one he had answered hours before, so advice
# about who to go and write to was given blind and was wrong. They go into
# state["answered"] now, keyed by row id, and are still never printed.
SELF_NAMES = {"shin234"}


# The site's edge starts answering 403 when the pages are asked for in quick
# succession, and adding a second mod doubled the number of pages a pass wants.
# Four back to back was enough to earn it. A few seconds between them is plenty
# and costs nothing, since a pass runs every ten minutes.
_last_fetch = [0.0]
FETCH_GAP = 4.0
# The edge sheds a request now and then and answers 403 rather than a page. On
# 15 September 2026 the bugs tab did that about half the time for a few minutes
# while the posts tab was untouched, so a single refusal says nothing about
# whether the page is reachable. Ask again before believing it.
RETRIES = 3
RETRY_GAP = (3.0, 9.0)


def _run(args, what):
    """Run curl up to RETRIES times, returning the body of the first success."""
    last = 0
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(RETRY_GAP[min(attempt - 1, len(RETRY_GAP) - 1)])
        r = subprocess.run(args, capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
        last = r.returncode
        _last_fetch[0] = time.time()
    raise RuntimeError("curl exit %d after %d attempts (%s)" % (last, RETRIES, what))


def fetch(url):
    # curl, because the site's edge answers urllib with a 403 and curl with
    # the page, on the same user agent.
    wait = FETCH_GAP - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    _last_fetch[0] = time.time()
    return _run(["curl", "-s", "-f", "-A", UA, "--max-time", "60", url], url)


def post(url, data, referer):
    """POST a form and return the body. Same rate limit as fetch().

    The site answers this endpoint 403 without the headers a browser's XHR
    sends, which is what made it look unreachable: X-Requested-With is the one
    that matters, and Referer and Origin cost nothing to send.
    """
    wait = FETCH_GAP - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    _last_fetch[0] = time.time()
    return _run(["curl", "-s", "-f", "-A", UA, "--max-time", "60",
                 "-X", "POST", url,
                 "-H", "X-Requested-With: XMLHttpRequest",
                 "-H", "Referer: " + referer,
                 "-H", "Origin: https://www.nexusmods.com",
                 "-H", "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
                 "--data", data], url)


def clean(s):
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def posts(page=MOD):
    """{comment id: (author, date, text)} for page one of the posts tab."""
    h = fetch(page + "?tab=posts")
    out = {}
    for m in re.finditer(r'id="comment-(\d+)"(.*?)<ul class="comment-inline', h, re.S):
        cid, body = m.group(1), m.group(2)
        a = re.search(r'class="comment-name">\s*<a[^>]*>\s*([^<]+?)\s*</a>', body)
        d = re.search(r'data-date="(\d+)"[^>]*>([^<]+)</time>', body)
        t = re.search(r'id="comment-content-\d+"[^>]*>(.*?)</div>', body, re.S)
        out[cid] = (a.group(1) if a else "?", d.group(2) if d else "?", clean(t.group(1))[:700] if t else "")
    return out


def bugs(page=MOD):
    """{issue id: (title, status, when)} for the bugs tab.

    `when` is the row's own last-activity stamp, and it is the only thing on this
    page that moves when somebody replies inside a row. The status can stay
    Fixed and the title never changes, so without it a reply is invisible.
    """
    h = fetch(page + "?tab=bugs")
    out = {}
    for m in re.finditer(r'id="issue_(\d+)"(.*?)</tr>', h, re.S):
        iid, body = m.group(1), m.group(2)
        t = re.search(r'class="issue-title"[^>]*>(.*?)</a>', body, re.S)
        s = re.search(r'inline-status"><span[^>]*>([^<]+)</span>', body)
        w = re.search(r'<time[^>]*>([^<]+)</time>', body)
        out[iid] = (clean(t.group(1)) if t else "?",
                    s.group(1).strip() if s else "?",
                    clean(w.group(1)) if w else "")
    return out


def bug_replies(iid, page=MOD):
    """[(reply id, author, when, text)] for one bugs-tab row, oldest first.

    The opening report is in here too, under the issue id rather than a reply
    id, so a brand new row reports its body and not just its title.
    """
    h = post("https://www.nexusmods.com/Core/Libs/Common/Widgets/ModBugReplyList",
             "issue_id=" + str(iid), page + "?tab=bugs")
    out = []
    tile = re.compile(r'id="bug-(?:issue|reply)-tile-(\d+)"(.*?)(?=id="bug-(?:issue|reply)-tile-|\Z)', re.S)
    for m in tile.finditer(h):
        rid, body = m.group(1), m.group(2)
        a = re.search(r'class="comment-name">\s*(?:<a[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*<', body)
        c = re.search(r'class="comment-content"[^>]*>(.*?)</div>\s*</li>', body, re.S)
        if not c:
            c = re.search(r'class="comment-content"[^>]*>(.*?)\Z', body, re.S)
        when, text = "", ""
        if c:
            inner = c.group(1)
            w = re.search(r'<time[^>]*>([^<]+)</time>', inner)
            when = clean(w.group(1)) if w else ""
            # Everything after the stamp is what they wrote. The stamp lives
            # inside the content block, so stripping tags without cutting it out
            # first prints the date twice.
            text = clean(inner[inner.find("</time>") + len("</time>"):] if w else inner)
        out.append((rid, a.group(1) if a else "?", when, text))
    return out


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        return []
    try:
        return json.loads(r.stdout)
    except ValueError:
        return []


def github(since):
    """Every repo, each line tagged with the mod it belongs to.

    A repo that answers with an error is skipped for this pass rather than
    killing the whole thing: one of the three being unreachable should not cost
    the other two, and `since` is not advanced by a failed pass anyway.
    """
    lines = []
    for _suffix, tag, repo in REPOS:
        try:
            for it in gh("repos/%s/issues?state=all&since=%s&per_page=50" % (repo, since)):
                if it.get("pull_request"):
                    continue
                if it["created_at"] > since and it["user"]["login"] != "shin2344234":
                    lines.append("%sgithub: new issue #%d by %s: %s"
                                 % (tag, it["number"], it["user"]["login"], it["title"]))
            for c in gh("repos/%s/issues/comments?since=%s&per_page=50" % (repo, since)):
                if c["created_at"] > since and c["user"]["login"] != "shin2344234":
                    n = c["issue_url"].rsplit("/", 1)[-1]
                    lines.append("%sgithub: comment on #%s by %s: %s"
                                 % (tag, n, c["user"]["login"], clean(c["body"])[:500]))
        except Exception as e:
            lines.append("watch: %s could not be read this pass (%s); the next pass picks it up"
                         % (repo, str(e)[:80]))
    return lines


def discord_token():
    tok = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not tok and os.path.exists(KEYFILE):
        for line in open(KEYFILE, encoding="utf-8"):
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"')
    return tok


def dapi(path, token):
    req = urllib.request.Request("https://discord.com/api/v10" + path,
                                 headers={"Authorization": "Bot " + token, "User-Agent": "MasterLooterWatch (https://github.com/shin2344234/master-looter, 1)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def discord(st, seeded, token):
    """New threads and new replies in the forum. State is {thread id: last
    message id seen}; a thread whose last message id has not moved costs no
    call, so a quiet pass is one request."""
    lines = []
    known = st.setdefault("discord", {})
    act = dapi("/guilds/%s/threads/active" % DISCORD_GUILD, token).get("threads", [])
    for t in act:
        if t.get("parent_id") != DISCORD_FORUM:
            continue
        tid, last, name = t["id"], known.get(t["id"]), t.get("name", "?")
        newest = t.get("last_message_id") or tid
        if not seeded:
            known[tid] = newest
            continue
        if last is not None and last == newest:
            continue
        msgs = dapi("/channels/%s/messages?limit=100&after=%s" % (tid, last or "0"), token)
        for m in sorted(msgs, key=lambda m: int(m["id"])):
            a = m.get("author") or {}
            if a.get("id") in DISCORD_SELF:
                continue
            what = "new thread" if m["id"] == tid else "reply"
            body = clean(m.get("content", "")) or ("(%d attachment(s))" % len(m.get("attachments", [])))
            lines.append("discord: %s in %s by %s: %s: %s" % (what, DISCORD_FORUM_NAME, a.get("username", "?"), name, body[:500]))
        if last is None and all((m.get("author") or {}).get("id") in DISCORD_SELF for m in msgs):
            lines.append("discord: new thread in %s: %s" % (DISCORD_FORUM_NAME, name))
        known[tid] = max([newest] + [m["id"] for m in msgs], key=int)
    return lines


def updates_channel():
    """Where a pass's findings are posted, alongside printing them. Read from
    the environment or keys.local.env rather than written down here: the channel
    is a private one and this file is public. Without it the watch still runs
    and still prints, it just posts nowhere.

    Printing alone is not enough, which is the reason this exists. The session
    running the watch is not always in front of anyone, and a report can sit in
    it unseen for hours.
    """
    v = os.environ.get("ML_UPDATES_CHANNEL", "").strip()
    if not v and os.path.exists(KEYFILE):
        for line in open(KEYFILE, encoding="utf-8"):
            line = line.strip()
            if line.startswith("ML_UPDATES_CHANNEL="):
                v = line.split("=", 1)[1].strip().strip('"')
    return v


def dpost(channel, content, token):
    body = json.dumps({"content": content,
                       "allowed_mentions": {"users": [SETH]}}).encode("utf-8")
    req = urllib.request.Request(
        "https://discord.com/api/v10/channels/%s/messages" % channel, data=body, method="POST",
        headers={"Authorization": "Bot " + token, "Content-Type": "application/json",
                 "User-Agent": "MasterLooterWatch (https://github.com/shin2344234/master-looter, 1)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()


# What each kind of find is, in words, and where to go and read it. The stdout
# lines are terse on purpose, since they are read by whoever is watching the
# session; a message arriving on a phone has to stand on its own.
SOURCES = [
    ("glint nexus post: ",  "Glint Spotter, posts tab", GLINT + "?tab=posts"),
    ("glint nexus bug: ",   "Glint Spotter, bugs tab",  GLINT + "?tab=bugs"),
    ("glint github: ",      "Glint Spotter, GitHub",    "https://github.com/shin2344234/glint-spotter/issues"),
    ("glint watch: ",       "Glint Spotter, the watcher itself", None),
    ("flight nexus post: ", "Flight Freedom, posts tab", FLIGHT + "?tab=posts"),
    ("flight nexus bug: ",  "Flight Freedom, bugs tab",  FLIGHT + "?tab=bugs"),
    ("flight github: ",     "Flight Freedom, GitHub",   "https://github.com/shin2344234/flight-freedom/issues"),
    ("flight watch: ",      "Flight Freedom, the watcher itself", None),
    ("nexus post: ",        "Master Looter, posts tab", MOD + "?tab=posts"),
    ("nexus bug: ",         "Master Looter, bugs tab",  MOD + "?tab=bugs"),
    ("github: ",            "Master Looter, GitHub",    "https://github.com/" + GH + "/issues"),
    ("discord: ",           "Discord, " + DISCORD_FORUM_NAME + " (any of the three mods)", None),
    ("watch: ",             "The watcher itself",       None),
]


def describe(line):
    """(heading, text, link) for one find, or a plain line if it is none of the
    known shapes."""
    for prefix, label, url in SOURCES:
        if line.startswith(prefix):
            return label, line[len(prefix):], url
    return "", line, None


def notify(lines, token):
    """Hand the pass's findings to the updates channel. Never lets a Discord
    problem end the watch: a failed post is worth one line on stdout and
    nothing more, because the events themselves have already been printed."""
    channel = updates_channel()
    if not lines or not token or not channel:
        return
    when = time.strftime("%H:%M")
    head = "<@%s> **%d new thing%s on the boards**, %s" % (
        SETH, len(lines), "" if len(lines) == 1 else "s", when)
    items = []
    for l in lines:
        label, text, url = describe(l)
        piece = "\n\n**%s**\n%s" % (label, text) if label else "\n\n%s" % text
        if url:
            piece += "\n<%s>" % url
        items.append(piece)
    chunks, body = [], head
    for piece in items:
        if len(body) + len(piece) > 1900:
            chunks.append(body)
            body = "(continued)"
        body += piece
    chunks.append(body)
    for c in chunks:
        try:
            dpost(channel, c, token)
        except Exception as e:
            print("watch: could not post to the updates channel: %s" % e)
            return


_skips = {}


class Held(Exception):
    """This page was skipped on purpose. Not a refusal, so it must not count as
    one: counting it would let the backoff feed itself and grow without the site
    having said no again."""


def load():
    try:
        return json.load(io.open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(st):
    io.open(STATE, "w", encoding="utf-8").write(json.dumps(st, indent=1))


def once(st):
    lines = []
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    seeded = bool(st)
    # Rows Seth has answered himself, id -> when. Seeded from what was saved
    # rather than started empty, because a row's replies are only re-read when
    # its timestamp moves, so a fresh dict would forget every thread that had
    # since gone quiet.
    answered = dict(st.get("answered", {}))
    fails = st.setdefault("fails", {})
    # A page that has just refused us is left alone for a pass or two rather
    # than asked again on the dot, which is what turns a moment of edge
    # blocking into an hour of it. The skip counter is not saved: a restart is
    # a fresh start and the state file already stops anything being replayed.
    def hold(key):
        n = fails.get(key, 0)
        if n < 3:
            return False
        skip = _skips.setdefault(key, 0)
        if skip > 0:
            _skips[key] = skip - 1
            return True
        _skips[key] = min(2 ** (n - 3), 6)
        return False

    for suffix, tag, page in BOARDS:
        pk, bk = "posts" + suffix, "bugs" + suffix
        # A board added after the state file was written seeds itself quietly on
        # its first pass, whatever the file says about the others.
        fresh = pk not in st
        try:
            if hold(pk):
                raise Held()
            p = posts(page)
            seen = set(st.get(pk, []))
            for cid, (a, d, t) in p.items():
                # Seth's own replies are not news; the watch exists for everyone else.
                if seeded and not fresh and cid not in seen and a != "shin234":
                    lines.append("%snexus post: %s, %s: %s" % (tag, a, d, t))
            st[pk] = sorted(seen | set(p))[-400:]
        except Held:
            pass
        except Exception as e:  # a failed fetch is not news until it keeps failing
            fails[pk] = fails.get(pk, 0) + 1
            if fails[pk] == 3:
                lines.append("%swatch: the posts tab has refused three passes running (%s). Backing off; "
                             "nothing is lost, the next pass that gets through catches up." % (tag, e))
        else:
            fails[pk] = 0
        try:
            if hold(bk):
                raise Held()
            b = bugs(page)
            old = st.get(bk, {})
            # Reply ids seen, flat across rows: the site numbers them globally,
            # so there is nothing to gain from keeping them per row.
            rk = bk + "_replies"
            seen_replies = set(st.get(rk, []))
            seeding_replies = rk not in st
            asked = 0
            for iid, (t, s, w) in sorted(b.items()):
                was = old.get(iid)
                # Ask a row for its replies when it is new, or when its own
                # timestamp has moved. A row marked Fixed still counts: both
                # findings of 14 September 2026 were replies on rows nobody had
                # a reason to look at.
                moved = was is None or (len(was) > 2 and was[2] != w)
                if not (moved or seeding_replies):
                    continue
                try:
                    replies = bug_replies(iid, page)
                except Exception as e:
                    print("%swatch: could not read the replies on row %s (%s). Nothing is lost, "
                          "the next pass that gets through catches up." % (tag, iid, e))
                    continue
                asked += 1
                for rid, who, rwhen, text in replies:
                    if rid in seen_replies:
                        continue
                    seen_replies.add(rid)
                    if not seeded or fresh or seeding_replies:
                        continue
                    if who.lower() in SELF_NAMES:
                        answered["%s%s" % (tag or "ml ", iid)] = rwhen
                        continue
                    lines.append("%snexus bug: reply on %s by %s, %s: %s [row: %s]"
                                 % (tag, iid, who, rwhen, text[:500], t))
            if seeding_replies and asked:
                print("%swatch: bug-row replies seeded from %d row(s); only new ones are reported from here."
                      % (tag, asked))
            st[rk] = sorted(seen_replies)
            st["answered"] = answered
            for iid, (t, s, w) in b.items():
                if not seeded or fresh:
                    continue
                if iid not in old:
                    lines.append("%snexus bug: new row %s [%s]: %s" % (tag, iid, s, t))
                elif old[iid][1] != s:
                    lines.append("%snexus bug: %s now %s (was %s): %s" % (tag, iid, s, old[iid][1], t))
            st[bk] = {k: list(v) for k, v in b.items()}
        except Held:
            pass
        except Exception as e:
            fails[bk] = fails.get(bk, 0) + 1
            if fails[bk] == 3:
                lines.append("%swatch: the bugs tab has refused three passes running (%s). Backing off; "
                             "nothing is lost, the next pass that gets through catches up." % (tag, e))
        else:
            fails[bk] = 0
        if fresh and seeded:
            lines.append("%swatch: seeded with %d comments and %d bug rows" % (
                tag, len(st.get(pk, [])), len(st.get(bk, {}))))
    since = st.get("github_since")
    if since:
        lines.extend(github(since))
    st["github_since"] = now
    token = discord_token()
    if token:
        try:
            lines.extend(discord(st, "discord" in st, token))
        except Exception as e:
            fails["discord"] = fails.get("discord", 0) + 1
            if fails["discord"] == 3:
                lines.append("watch: discord fetch has failed three passes running: %s" % e)
        else:
            fails["discord"] = 0
    save(st)
    if not seeded:
        lines.append("watch: seeded with %d comments and %d bug rows; github from %s; discord %s" % (
            len(st.get("posts", [])), len(st.get("bugs", {})), now,
            "%d threads" % len(st.get("discord", {})) if token else "not watched (no DISCORD_BOT_TOKEN)"))
    elif token and "discord" in st and st.get("discord_seeded_at") is None:
        st["discord_seeded_at"] = now
        save(st)
        lines.append("watch: discord seeded with %d active threads in %s" % (len(st["discord"]), DISCORD_FORUM_NAME))
    notify(lines, token)
    return lines


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    st = load()
    if "--once" in sys.argv:
        for l in once(st):
            print(l)
        return
    while True:
        for l in once(st):
            print(l)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
