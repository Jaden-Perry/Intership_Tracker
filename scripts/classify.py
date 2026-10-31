"""Keyword-based eligibility classifier for internship posting titles/links.

Buckets:
  - "open_now"         sophomore-eligible program (named early-talent tracks:
                        Sophomore/Discovery/Insight/Possibilities/FOCUS/etc.)
  - "not_yet_eligible"  junior-year Summer Analyst / Summer Associate seat,
                        for any class year — a rising sophomore isn't eligible
                        for either the current cycle or next year's
  - "unknown"           matched a tracked keyword but couldn't confidently classify

Note on class-year labels: firms label "Summer Analyst" postings by the
summer the internship happens ("20XX Summer Analyst" = internship in summer
20XX, for whoever graduates in 20XX+1), not by how far out recruiting opens.
For this user (rising sophomore as of fall 2026), that internship summer is
2028 — so a "2028 Summer Analyst" posting is genuinely THEIR class, no
matter which firm posts it or how early. Firms increasingly recruit that far
ahead directly from the sophomore pool (confirmed on Evercore's actual 2028
Summer Analyst posting: "graduation date between December 2028 and June
2029" — exactly this user's class), without a separately-branded sophomore
program. Any other year (2026, 2027, 2029+) belongs to a different class and
stays not_yet_eligible even though the phrasing is identical.
"""
import re
import unicodedata

# The Summer Analyst year that lines up with this user's own class. Update
# this if the user's actual class year changes (e.g. it should become "2029"
# once they become a rising junior).
ELIGIBLE_SUMMER_ANALYST_YEAR = "2028"
# Some firms label the same program by graduating class instead, e.g. Houlihan
# Lokey's "2028 Summer Financial Analyst ... (Class of 2029)". Class of 2029
# graduates in 2029, i.e. the same class that does the Summer 2028 internship.
ELIGIBLE_CLASS_YEAR = "2029"

# "Summer Analyst" including firm-specific variants like "Summer Financial
# Analyst" (Houlihan Lokey) -- up to two words between "Summer" and "Analyst".
SUMMER_ANALYST_PATTERN = r"\bsummer\s+(?:[\w&\-]+\s+){0,2}analyst\b"

# Firm-specific named sophomore programs. Kept in one place and folded into
# both SOPHOMORE_PATTERNS and CANDIDATE_KEYWORDS below, since a program name
# that isn't in CANDIDATE_KEYWORDS would get filtered out by is_candidate()
# before classify() ever sees it.
NAMED_SOPHOMORE_PROGRAMS = [
    r"\bpossibilities\s+series\b",
    r"\bxceleration\b",
    r"\bpathways?\b",
    r"\bfocus program\b",
    r"\bblackstone\s+launchpad\b",    # Blackstone LaunchPad (bare "launchpad" matched an unrelated Ares role)
    r"\bwinning women\b",
    r"\blaunching leaders\b",
    r"\bcareer exploration\b",       # Piper Sandler CEP
    r"\bcatalyst program\b",         # Warburg Pincus
    r"\bdistinguished scholars\b",   # Silver Lake
    r"\baccelerate program\b",       # Advent International
    r"\bpimco prep\b",               # PIMCO
    r"\bstrategic resources\b",      # William Blair
    r"\bfast track to investment banking\b",  # William Blair sophomore event; final round feeds its 2028 Summer Analyst class
]

# "Discovery"/"Insight(s)" alone are too generic for a candidate/sophomore
# signal — they also show up as team or product names on ordinary full-time
# roles (e.g. Fidelity's "Manager, Analytics & Performance Insights"). Require
# internship-shaped context around them. Shared between SOPHOMORE_PATTERNS and
# CANDIDATE_KEYWORDS so both stay in sync.
_DISCOVERY_PATTERN = r"\bdiscovery\b.{0,20}\b(program|internship|day|week)\b"
_INSIGHT_DAY_PATTERN = r"\binsights?\s+(day|days|week|weeks|forum|program|programs|summit)\b"
_EARLY_INSIGHT_PATTERN = r"\bearly[- ]?insight[s]?\b"

SOPHOMORE_PATTERNS = [
    r"\bsophomores?\b",
    r"\bfreshm[ae]n\b",
    r"\bfirst[- ]?years?\b",
    r"\bunderclassm[ae]n\b",
    _DISCOVERY_PATTERN,
    _INSIGHT_DAY_PATTERN,
    _EARLY_INSIGHT_PATTERN,
    r"\bwomen'?s?\s+(program|network|summit)\b",
    r"\bdiversity\s+(program|summit|initiative)\b",
    r"\b(spring|winter)\s+(week|program|insight)\b",
    *NAMED_SOPHOMORE_PROGRAMS,
]

JUNIOR_PATTERNS = [
    SUMMER_ANALYST_PATTERN,
    r"\binvestment\s+banking\s+analyst\b",
    r"\bjunior\s+year\b",
    r"\brising\s+senior\b",
]

# Generic keywords used to decide whether a link is even a candidate posting worth
# tracking in the first place (applied before classification). Deliberately
# narrower than a bare "analyst"/"program"/"202X" match, which would sweep in
# unrelated full-time job-board listings (e.g. "Senior Investment Analyst").
CANDIDATE_KEYWORDS = [
    r"\bintern(ship)?\b",
    SUMMER_ANALYST_PATTERN,
    r"\bsummer\s+associate\b",
    r"\bsophomores?\b",
    r"\bfreshm[ae]n\b",
    _DISCOVERY_PATTERN,
    _INSIGHT_DAY_PATTERN,
    _EARLY_INSIGHT_PATTERN,
    r"\bpossibilities\b",
    r"\bearly[- ]?career\b",
    r"\bstudent[s]?\b",
    r"\bcampus\b",
    r"\bundergrad(uate)?\b",
    r"\bexternship\b",
    *NAMED_SOPHOMORE_PROGRAMS,
]

# Common full-time/professional job-title markers. If one of these shows up
# WITHOUT any accompanying internship-specific signal (intern, summer
# analyst/associate, sophomore/freshman, student, campus, undergrad,
# externship, or a named sophomore program), the posting is a full-time role
# that only matched CANDIDATE_KEYWORDS incidentally (e.g. a department name
# like "Performance Insights") and should be dropped rather than surfaced as
# "needs review." This is a general safety net, not tied to any one firm.
FULL_TIME_ROLE_MARKERS = [
    r"\bmanager\b", r"\bdirector\b", r"\bvice president\b", r"\bvp\b",
    r"\bhead of\b", r"\bsenior\b", r"\blead\b", r"\bofficer\b",
    r"\bengineer\b", r"\bspecialist\b", r"\bconsultant\b", r"\bprincipal\b",
    r"\bchief\b", r"\bexecutive\b", r"\badministrator\b", r"\bcoordinator\b",
    r"\bsupervisor\b",
]
STRONG_INTERNSHIP_SIGNALS = [
    r"\bintern(ship)?\b",
    SUMMER_ANALYST_PATTERN,
    r"\bsummer\s+associate\b",
    r"\bsophomores?\b",
    r"\bfreshm[ae]n\b",
    r"\bstudent[s]?\b",
    r"\bcampus\b",
    r"\bundergrad(uate)?\b",
    r"\bexternship\b",
    *NAMED_SOPHOMORE_PROGRAMS,
]
_full_time_re = re.compile("|".join(FULL_TIME_ROLE_MARKERS), re.IGNORECASE)
_strong_internship_re = re.compile("|".join(STRONG_INTERNSHIP_SIGNALS), re.IGNORECASE)


# Engineering/IT roles. Applied even to internships ("Software Engineer Summer
# Intern" has an internship signal, so is_full_time_role() lets it through).
# "Technology" alone is NOT a marker: it is also an investment-banking coverage
# group (Lazard "Summer Analyst - Boston Technology", Evercore "Global
# Technology"). Only the IT-division title shapes seen on real boards are matched:
# "Technology Summer Analyst" (BofA/Wells Fargo), "Technology, Application
# Development, ..." (Citi) and Piper's "Summer Internship Program - Technology".
ENGINEERING_ROLE_MARKERS = [
    r"\bengineer(s|ing)?\b", r"\bsoftware\b", r"\bdevelopers?\b", r"\bdevops\b",
    r"\bfull[- ]?stack\b", r"\bmainframe\b", r"\bcyber\s*security\b", r"\bcyber\b",
    r"\binformation security\b", r"\bapplication development\b", r"\bproduction support\b",
    r"\bmachine learning\b", r"\bdata scien(ce|tist)s?\b",
    r"\btechnology\s+summer\s+(analyst|intern(ship)?)\b",
    r"^\s*(\d{4}\s+)?technology\s*[,:\-–]",
    r"\bsummer\s+internship\s+program\s*[-–]\s*technology\b",
]
_engineering_re = re.compile("|".join(ENGINEERING_ROLE_MARKERS), re.IGNORECASE)


def is_engineering_role(text: str) -> bool:
    """Whether a title is an engineering/software/IT role (not wanted)."""
    return bool(_engineering_re.search(text or ""))


_recruiter_job_re = re.compile(
    r"\brecruit(er|ing)\s+(coordinator|associate|analyst|manager|partner|specialist)\b", re.IGNORECASE)


def is_full_time_role(text: str) -> bool:
    """Whether a title looks like a full-time/professional role rather than
    an internship, i.e. it has a full-time marker and no internship signal."""
    text = text or ""
    if _recruiter_job_re.search(text):
        return True  # e.g. "Campus Recruiting Analyst": an HR job, not an internship
    return bool(_full_time_re.search(text) and not _strong_internship_re.search(text))

# Region codes and city/country names that unambiguously mean a posting is
# NOT in the US. Firms tag postings this way in the title itself (e.g.
# "2027 | APEJ | Hong Kong | ..."). Deliberately does NOT include "Americas"
# as a region code, since firms use that tag for a mix of US/Canada/Latin
# America postings and it would wrongly exclude genuine US ones — city/country
# names are the precise signal instead. A title with no location markers at
# all is left alone (not assumed non-US).
NON_US_LOCATION_MARKERS = [
    r"\bemea\b", r"\bapac\b", r"\bapej\b", r"\bapj\b", r"\blatam\b",
    # Asia-Pacific
    r"\bhong kong\b", r"\bsingapore\b", r"\btokyo\b", r"\bosaka\b", r"\bjapan\b", r"\btaipei\b", r"\btaiwan\b",
    r"\bseoul\b", r"\bkorea\b", r"\bshanghai\b", r"\bbeijing\b", r"\bshenzhen\b", r"\bchina\b",
    r"\bmumbai\b", r"\bbangalore\b", r"\bbengaluru\b", r"\bdelhi\b", r"\bpune\b", r"\bhyderabad\b",
    r"\bchennai\b", r"\bgurgaon\b", r"\bgurugram\b", r"\bnoida\b", r"\bindia\b",
    r"\bmanila\b", r"\bphilippines\b", r"\bkuala lumpur\b", r"\bmalaysia\b", r"\bjakarta\b", r"\bbangkok\b",
    r"\bsydney\b", r"\bmelbourne\b", r"\bbrisbane\b", r"\bperth\b(?!\s+amboy)", r"\baustralia\b", r"\bauckland\b", r"\bnew zealand\b",
    # UK, Ireland, Europe
    r"\blondon\b", r"\bunited kingdom\b", r"\bu\.?k\.?\b", r"\bengland\b", r"\bscotland\b", r"\bwales\b",
    r"\bglasgow\b", r"\bedinburgh\b", r"\bknutsford\b", r"\bmanchester\b(?!,?\s*(nh|ct|new hampshire|connecticut))", r"\bnorthampton\b", r"\bbelfast\b",
    r"\bleeds\b", r"\bcardiff\b", r"\bjersey\b(?!\s+city)", r"\bguernsey\b", r"\bmonaco\b",
    r"\bdublin\b(?!,?\s*(oh|ca|ga|tx|va|ohio|california|georgia))", r"\bireland\b",
    r"\bfrankfurt\b", r"\bmunich\b", r"\bmunchen\b", r"\bberlin\b", r"\bhamburg\b", r"\bdusseldorf\b", r"\bgermany\b",
    r"\bparis\b", r"\bfrance\b", r"\bzurich\b", r"\bgeneva\b", r"\bswitzerland\b",
    r"\bstockholm\b", r"\bsweden\b", r"\bcopenhagen\b", r"\bdenmark\b", r"\boslo\b", r"\bnorway\b", r"\bhelsinki\b", r"\bfinland\b",
    r"\bwarsaw\b", r"\bwarszawa\b", r"\bpoland\b", r"\bbudapest\b", r"\bhungary\b", r"\bprague\b", r"\bbucharest\b", r"\bromania\b",
    r"\bamsterdam\b", r"\bnetherlands\b", r"\bbrussels\b", r"\bbelgium\b", r"\bluxembourg\b",
    r"\bmadrid\b", r"\bbarcelona\b", r"\bspain\b", r"\blisbon\b", r"\bportugal\b",
    r"\bmilan\b", r"\bmilano\b", r"\bitaly\b", r"\baustria\b", r"\bgreece\b", r"\bistanbul\b", r"\bturkey\b",
    # Middle East / Africa
    r"\bdubai\b", r"\babu dhabi\b", r"\bu\.?a\.?e\.?\b", r"\briyadh\b", r"\bsaudi\b", r"\bdoha\b", r"\bqatar\b", r"\bkuwait\b", r"\bbahrain\b",
    r"\btel aviv\b", r"\bisrael\b", r"\bcairo\b", r"\begypt\b", r"\bjohannesburg\b", r"\bcape town\b", r"\bsouth africa\b", r"\blagos\b", r"\bnairobi\b",
    # Canada
    r"\btoronto\b", r"\bmontreal\b", r"\bvancouver\b", r"\bcalgary\b", r"\bottawa\b", r"\bcanada\b",
    r"\bquebec\b", r"\bontario\b", r"\balberta\b", r"\bbritish columbia\b", r",\s*(qc|can)\b",
    # Latin America
    r"(?<!new )\bmexico\b", r"\bsao paulo\b", r"\bbrazil\b", r"\bbogota\b", r"\bcolombia\b", 
    r"\bsantiago\b", r"\bchile\b", r"\bbuenos aires\b", r"\bargentina\b", r"\bcosta rica\b",
]
_non_us_re = re.compile("|".join(NON_US_LOCATION_MARKERS), re.IGNORECASE)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def is_non_us_location(text: str) -> bool:
    """Whether a title contains a clear non-US location marker."""
    return bool(_non_us_re.search(_strip_accents(text or "")))


_sophomore_re = re.compile("|".join(SOPHOMORE_PATTERNS), re.IGNORECASE)
_junior_re = re.compile("|".join(JUNIOR_PATTERNS), re.IGNORECASE)
_candidate_re = re.compile("|".join(CANDIDATE_KEYWORDS), re.IGNORECASE)


def is_candidate(text: str) -> bool:
    """Whether a link's text is worth tracking at all."""
    return bool(_candidate_re.search(text or ""))


_eligible_year_re = re.compile(rf"\b{ELIGIBLE_SUMMER_ANALYST_YEAR}\b")
_class_of_re = re.compile(r"\bclass of (\d{4})\b", re.IGNORECASE)


def _is_eligible_year(text: str) -> bool:
    """True for a "2028" program label or "Class of 2029". A "Class of 2028" is
    the class ahead of this user, so its "2028" must not count as the program year."""
    classes = _class_of_re.findall(text)
    if ELIGIBLE_CLASS_YEAR in classes:
        return True
    return bool(_eligible_year_re.search(_class_of_re.sub("", text)))


# Undergraduate summer programs. Deliberately excludes "Summer Associate":
# banks use that name for MBA/JD interns (e.g. Lazard's posting requires being
# "matriculated at a MBA or JD program"), not undergrads, so it can never be
# open to this user whatever the year. "Summer Internship" is included because
# some firms (e.g. Wells Fargo: "2028 Investment Banking Summer Internship")
# don't use the "Summer Analyst" name for the same undergraduate program.
_summer_program_re = re.compile(SUMMER_ANALYST_PATTERN + r"|\bsummer\s+intern(ship)?s?\b", re.IGNORECASE)

_graduate_re = re.compile(r"\b(mba|j\.?d|ph\.?d|master'?s?|post-?graduate)\b", re.IGNORECASE)
_summer_associate_re = re.compile(r"\bsummer\s+associate\b", re.IGNORECASE)
_undergrad_hint_re = re.compile(r"\b(undergrad\w*|sophomore\w*|freshm[ae]n|bachelor\w*)\b", re.IGNORECASE)


def is_graduate_level(text: str, summer_associate_is_graduate: bool = False) -> bool:
    """MBA/JD/PhD-level programs, which an undergraduate can't apply to. A bare
    "Summer Associate" counts only for firms whose Summer Associate program was
    verified as MBA-only (Lazard, JPMorgan, Wells Fargo); at others (e.g. Capital
    Group's undergraduate CAP) the title alone doesn't say. An explicit
    undergraduate hint overrides."""
    text = text or ""
    if _undergrad_hint_re.search(text):
        return False
    if _graduate_re.search(text):
        return True
    return summer_associate_is_graduate and bool(_summer_associate_re.search(text))


def classify(text: str) -> str:
    """Classify posting text into open_now / not_yet_eligible / unknown.

    Sophomore signals are checked first: a title like "2027 Sophomore Summer
    Analyst Program" would match both JUNIOR_PATTERNS ("summer analyst") and
    SOPHOMORE_PATTERNS ("sophomore") — sophomore wins since that's the actual
    eligibility signal for this user.

    A "Summer Analyst"/"Summer Associate" posting for ELIGIBLE_SUMMER_ANALYST_YEAR
    is also open_now, even with no sophomore branding — see module docstring.
    """
    text = text or ""
    if _sophomore_re.search(text):
        return "open_now"
    if _is_eligible_year(text) and _summer_program_re.search(text):
        return "open_now"
    if _junior_re.search(text):
        return "not_yet_eligible"
    return "unknown"
