"""Keyword-based eligibility classifier for internship posting titles/links.

Buckets:
  - "open_now"         sophomore-eligible program (named early-talent tracks:
                        Sophomore/Discovery/Insight/Possibilities/FOCUS/etc.)
  - "not_yet_eligible"  junior-year Summer Analyst / Summer Associate seat,
                        for any class year — a rising sophomore isn't eligible
                        for either the current cycle or next year's
  - "unknown"           matched a tracked keyword but couldn't confidently classify

Note: class-year labels ("2027", "2028") in a title are NOT used to decide
sophomore vs. junior eligibility — firms label Summer Analyst postings by the
summer the internship happens, not by program tier, so "2027 Summer Analyst"
and "2028 Summer Analyst" are both junior-level seats, just for different
class cohorts. Only the program *name* signals sophomore eligibility.
"""
import re

# Firm-specific named sophomore programs. Kept in one place and folded into
# both SOPHOMORE_PATTERNS and CANDIDATE_KEYWORDS below, since a program name
# that isn't in CANDIDATE_KEYWORDS would get filtered out by is_candidate()
# before classify() ever sees it.
NAMED_SOPHOMORE_PROGRAMS = [
    r"\bpossibilities\s+series\b",
    r"\bxceleration\b",
    r"\bpathways?\b",
    r"\bfocus program\b",
    r"\blaunchpad\b",
    r"\bleadership development program\b",
    r"\bldp\b",
    r"\bwinning women\b",
    r"\blaunching leaders\b",
    r"\bcareer exploration\b",       # Piper Sandler CEP
    r"\bcatalyst program\b",         # Warburg Pincus
    r"\bdistinguished scholars\b",   # Silver Lake
    r"\baccelerate program\b",       # Advent International
    r"\bpimco prep\b",               # PIMCO
    r"\bstrategic resources\b",      # William Blair
]

SOPHOMORE_PATTERNS = [
    r"\bsophomore\b",
    r"\bfreshman\b",
    r"\bfirst[- ]?year\b",
    r"\bunderclassm[ae]n\b",
    r"\bdiscovery\b.{0,20}\b(program|internship|day|week)\b",
    r"\binsight\s+(day|days|week|weeks|forum|program|summit)\b",
    r"\bearly[- ]?insight[s]?\b",
    r"\bexplore\s+opportunities\b",
    r"\bwomen'?s?\s+(program|network|summit)\b",
    r"\bdiversity\s+(program|summit|initiative)\b",
    r"\b(spring|winter)\s+(week|program|insight)\b",
    *NAMED_SOPHOMORE_PROGRAMS,
]

JUNIOR_PATTERNS = [
    r"\bsummer\s+analyst\b",
    r"\binvestment\s+banking\s+analyst\b",
    r"\bsummer\s+associate\b",
    r"\bjunior\s+year\b",
    r"\brising\s+senior\b",
]

# Generic keywords used to decide whether a link is even a candidate posting worth
# tracking in the first place (applied before classification). Deliberately
# narrower than a bare "analyst"/"program"/"202X" match, which would sweep in
# unrelated full-time job-board listings (e.g. "Senior Investment Analyst").
CANDIDATE_KEYWORDS = [
    r"\bintern(ship)?\b",
    r"\bsummer\s+analyst\b",
    r"\bsummer\s+associate\b",
    r"\bsophomore\b",
    r"\bfreshman\b",
    r"\bdiscovery\b",
    r"\binsight[s]?\b",
    r"\bpossibilities\b",
    r"\bearly[- ]?career\b",
    r"\bstudent[s]?\b",
    r"\bcampus\b",
    r"\bundergrad(uate)?\b",
    r"\bexternship\b",
    *NAMED_SOPHOMORE_PROGRAMS,
]

_sophomore_re = re.compile("|".join(SOPHOMORE_PATTERNS), re.IGNORECASE)
_junior_re = re.compile("|".join(JUNIOR_PATTERNS), re.IGNORECASE)
_candidate_re = re.compile("|".join(CANDIDATE_KEYWORDS), re.IGNORECASE)


def is_candidate(text: str) -> bool:
    """Whether a link's text is worth tracking at all."""
    return bool(_candidate_re.search(text or ""))


def classify(text: str) -> str:
    """Classify posting text into open_now / not_yet_eligible / unknown.

    Sophomore signals are checked first: a title like "2027 Sophomore Summer
    Analyst Program" would match both JUNIOR_PATTERNS ("summer analyst") and
    SOPHOMORE_PATTERNS ("sophomore") — sophomore wins since that's the actual
    eligibility signal for this user.
    """
    text = text or ""
    if _sophomore_re.search(text):
        return "open_now"
    if _junior_re.search(text):
        return "not_yet_eligible"
    return "unknown"
