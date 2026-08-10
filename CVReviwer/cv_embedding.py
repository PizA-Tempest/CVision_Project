"""
cv_embedding.py — semantic similarity between a CV and a job listing

Feature 2 support module. Answers one question token matching structurally
cannot: *are these the same kind of work?*

WHY THIS EXISTS
===============
compare_skills (M-02-03) compares skill names as strings. Measured across the
sample corpus, that leaves every CV with at least one developer listing
scoring exactly 0.000 on skills — not because matching is buggy, but because
the listings genuinely share no tokens with each other:

    Juni Developer        PHP, Python, D365BC, ERP, Magento
    Full Stack Developer  Golang, React, REST APIs, microservices
    Mobile Developer      Android SDK, Swift, Flutter, kotlin

A Vue/Node CV overlaps none of the first two at the token level. A human still
calls all three "software developer". Normalising spellings recovers some of
this (Node -> Node.js, MY SQL -> MySQL) but cannot invent an overlap that is
not there, so a purely lexical scorer cannot rank these above kitchen roles
for a developer CV.

Sentence embeddings can. Vectors for "Golang, REST APIs, microservices" and
"Vue.js, Node.js, Express.js" sit close together and both sit far from
"culinary leadership, menu design, food safety".

WHERE THE VECTORS COME FROM
===========================
job_enrichment.embedding is already populated by enrich_jobs.py — one
384-float MiniLM vector per listing, produced from build_embed_text(title,
skills). Nothing has read it until now. This module encodes the CV side in
the *same* text format with the *same* model so the two are comparable, then
takes the cosine.

MODEL MISMATCH IS CHECKED, NOT ASSUMED
======================================
Cosine similarity between vectors from different models is meaningless — it
returns a plausible number rather than an error, which is the worst kind of
wrong. enrich_jobs.py stores embedding_model and embedding_dim alongside each
vector precisely so this can be verified. A listing whose vector came from a
different model, or has a different dimension, is skipped: its semantic score
is None and the caller falls back to the lexical score alone.

COST
====
The model is ~400 MB and loads once per process, lazily — importing this
module does not load it. match_service imports this module lazily in turn, so
the test suite (which never asks for a semantic score) never pays for it.
"""

from __future__ import annotations

import json
import math
import re

# Must match enrich_jobs.MODEL_NAME. Not imported from there: enrich_jobs
# pulls in the OpenAI client and argparse machinery that has no business in
# the matching path.
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBED_TEXT_LIMIT = 500

# Similarity below this is treated as no relationship at all.
#
# MiniLM gives any two short strings a positive cosine — shared function
# words, shared "Title: ... | Skills: ..." scaffolding, shared Latin script.
# Measured on this corpus: developer listings average 0.30-0.55 against a
# software CV, kitchen listings 0.10-0.36. Nothing is ever near 0, so a raw
# cosine used directly as a 0-1 ratio spends its bottom third on a baseline
# that carries no information and flatters every unrelated listing.
#
# Subtracting the floor and rescaling the remainder puts that baseline at 0
# and gives the informative range the full scale. 0.0 disables it and uses
# the raw cosine. Swept by eval_matching.py --sweep.
#
# 0.2 chosen with SEMANTIC_GATE = 1.0. Higher floors zero out any listing
# whose cosine falls below them, which at a high gate zeroes the whole score;
# at 0.35 that flattened the ranking so far that margins tied at zero and no
# CV separated at all. See the note on SEMANTIC_GATE in match_service.py.
SEMANTIC_FLOOR = 0.2

_model = None
_cache: dict[str, list[float]] = {}


class EmbeddingUnavailable(Exception):
    """The model could not be loaded. Callers fall back to lexical scoring."""


def _load_model():
    """
    Loads the SentenceTransformer once per process.

    Imported inside the function, not at module level: embed.py's
    module-level ML imports are exactly the pattern TBD_and_Conflicts.md
    flags as a cost, and match_service must stay importable without a 400 MB
    load for the 110 unit tests that never touch this path.
    """
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as ex:
            raise EmbeddingUnavailable(
                "sentence-transformers is not installed; semantic scoring is off."
            ) from ex
        try:
            _model = SentenceTransformer(MODEL_NAME)
        except Exception as ex:
            raise EmbeddingUnavailable(f"Could not load {MODEL_NAME}: {ex}") from ex
    return _model


def build_cv_embed_text(cv_data) -> str:
    """
    The CV rendered in the same shape enrich_jobs gives a listing.

    build_embed_text produces "Title: {title} | Skills: {a b c}". Feeding the
    CV a different shape would compare a sentence against a fragment, and the
    similarity would partly measure formatting rather than content — so the
    most recent job title stands in for the listing's title, and the CV's
    skills for the listing's.

    The 500-character cap is build_embed_text's, kept deliberately: it is what
    the stored job vectors were produced under.
    """
    skills = []
    for entry in cv_data.get("skills") or []:
        name = entry.get("skill_name") if isinstance(entry, dict) else entry
        if name:
            skills.append(str(name))

    title = ""
    for role in cv_data.get("work_experience") or []:
        position = role.get("position") if isinstance(role, dict) else None
        if position:
            title = str(position)
            break
    if not title:
        # No work history — fall back to the field of study, which is the
        # only other statement of domain the CV makes. A CV with neither is
        # scored on skills alone, which is the honest answer.
        for entry in cv_data.get("education") or []:
            degree = entry.get("degree") if isinstance(entry, dict) else None
            if degree:
                title = re.sub(r"^(bachelor|master|doctor)[^,]*?\bin\b\s*", "",
                               str(degree), flags=re.I)
                break

    skills_str = " ".join(skills)
    if not title and not skills_str:
        return "general"
    return f"Title: {title} | Skills: {skills_str}"[:EMBED_TEXT_LIMIT]


def encode_cv(cv_data) -> list[float]:
    """
    Vector for one CV, cached by its embed text.

    Cached because the evaluation harness scores the same CV against every
    listing, and re-encoding identical text 19 times is pure waste.

    Throws:
        EmbeddingUnavailable — model missing or unloadable.
    """
    text = build_cv_embed_text(cv_data)
    if text not in _cache:
        _cache[text] = [float(x) for x in _load_model().encode(text)]
    return _cache[text]


def cosine_similarity(a, b):
    """
    Cosine of two vectors, clamped to [0, 1], with SEMANTIC_FLOOR removed.

    This originally rescaled the full [-1, 1] cosine range as (c + 1) / 2, on
    the reasoning that clamping negatives to 0 would lose the distinction
    between "unrelated" and "opposite". That reasoning was wrong for this
    data, and measurably so: MiniLM cosines here never approach -1. Developer
    listings scored 0.30-0.55 against a software CV and kitchen listings
    0.10-0.36, so the rescale mapped them to 0.65-0.78 and 0.55-0.68 —
    halving the gap and, worse, giving every kitchen listing a floor near
    0.55 on an axis where its token overlap was 0.0. Blending that in raised
    kitchen scores and made the worst margin worse rather than better.

    Clamping at 0 costs nothing real: a negative cosine and a zero cosine
    both mean "unrelated", and the sign carried no information worth the
    compression it forced on everything else.

    Returns None when either vector is missing or the lengths disagree —
    never a fabricated number.
    """
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    raw = max(0.0, min(1.0, dot / (na * nb)))

    floor = max(0.0, min(0.9, SEMANTIC_FLOOR))
    if floor <= 0.0:
        return raw
    return max(0.0, (raw - floor) / (1.0 - floor))


def listing_vector(listing):
    """
    The stored vector for a listing, or None when it cannot be trusted.

    Refuses rather than guesses on a model or dimension mismatch: comparing
    across models yields a plausible-looking number, not an error, so an
    unchecked comparison would silently score nonsense.
    """
    raw = listing.get("embedding")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, list) or not raw:
        return None

    stored_model = listing.get("embedding_model")
    if stored_model and stored_model != MODEL_NAME:
        return None
    stored_dim = listing.get("embedding_dim")
    if stored_dim and int(stored_dim) != len(raw):
        return None
    return [float(x) for x in raw]


def semantic_score(cv_vector, listing):
    """
    How close this listing is to this CV in meaning, 0.0–1.0, or None.

    None means "no opinion" — no vector, or one that cannot be compared — and
    the caller must fall back to the lexical score rather than treating it as
    zero, which would penalise a listing for an enrichment gap.
    """
    if not cv_vector:
        return None
    return cosine_similarity(cv_vector, listing_vector(listing))