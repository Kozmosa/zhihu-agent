"""Synthetic fixtures adapted from this project's scripts/ollama_testing/fixtures.py.

These fixtures test HTTP wiring and validation. They do not evaluate model quality.
All source text is hand-written demonstration material, not captured user data.
Only server-owned reference IDs and reading section indexes follow request data.
"""

CLAIM = "Active recall means retrieving learned information without looking at the source."
SOURCE_TEXT = (
    CLAIM
    + " A useful practice is to close your notes and explain the idea from memory."
    + " Afterwards, compare your explanation with the source and correct omissions."
)
OTHER_TEXT = (
    "Active recall asks learners to retrieve an idea from memory before checking notes."
    " Feedback can reveal errors in that attempt."
    " This describes a method, not proof that every learner will benefit equally."
)
IMPORT_BODY = {
    "items": [
        {
            "title": "Active recall practice",
            "author_id": "smoke-author",
            "author_name": "Smoke Author",
            "text": SOURCE_TEXT,
            "topics": ["Learning"],
            "origin": "demo",
        },
        {
            "title": "A separate account of active recall",
            "author_id": "smoke-author",
            "author_name": "Smoke Author",
            "text": OTHER_TEXT,
            "topics": ["Learning", "Feedback"],
            "origin": "demo",
        },
    ]
}


def model_response(prompt):
    task, payload = prompt["task"], prompt["input"]
    if task == "reading":
        return {
            "summary": "Recall from memory, then compare with the source and correct omissions.",
            "sections": [
                {
                    "index": section["index"],
                    "heading": "Active recall practice",
                    "key_points": ["Recall before consulting notes; check the result afterwards."],
                    "guiding_question": "How can checking the source reveal omissions?",
                }
                for section in reversed(payload["sections"])
            ],
        }
    if task == "cards":
        return {
            "cards": [
                {
                    "front": "What is active recall?",
                    "back": "Retrieve learned information without looking at the source.",
                    "evidence_excerpt": CLAIM,
                }
            ]
        }
    if task == "facts":
        return {
            "verdict": "supported",
            "explanation": "The supplied passage describes recall before consulting notes.",
            "assessments": [
                {
                    "evidence_id": payload["evidence"][0]["evidence_id"],
                    "relation": "supports",
                    "rationale": "Both descriptions retrieve information before checking notes.",
                }
            ],
            "conditions": ["This checks the method's description, not universal effectiveness."],
        }
    if task == "knowledge":
        evidence_id = payload["evidence"][0]["evidence_id"]
        return {
            "nodes": [
                {
                    "id": "recall",
                    "label": "Active recall",
                    "description": "Retrieve an idea from memory before reading notes.",
                    "evidence_ids": [evidence_id],
                },
                {
                    "id": "feedback",
                    "label": "Feedback",
                    "description": "Compare the recalled explanation with the source.",
                    "evidence_ids": [evidence_id],
                },
            ],
            "edges": [
                {
                    "id": "recall-feedback",
                    "source": "recall",
                    "target": "feedback",
                    "relation": "related",
                    "explanation": "The method pairs memory retrieval with source checking.",
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    if task == "author":
        return {
            "answer": "Recall the idea from memory, then check the source for omissions [1].",
            "citations": [1],
        }
    raise ValueError(f"Unexpected fixture task: {task}")


def api_requests(source_id):
    """Each tuple is a user-visible capability and a real public API request."""
    return [
        (
            "reading",
            "POST",
            "/api/v1/reading/analyze",
            {"source_id": source_id, "chunk_size": 100},
        ),
        ("cards", "POST", "/api/v1/cards/generate", {"source_id": source_id, "count": 2}),
        (
            "facts",
            "POST",
            "/api/v1/facts/review",
            {"claims": [CLAIM], "author_id": "smoke-author"},
        ),
        ("knowledge", "GET", "/api/v1/knowledge-map?author_id=smoke-author", None),
        (
            "author",
            "POST",
            "/api/v1/author/ask",
            {
                "author_id": "smoke-author",
                "question": "How should I practice active recall?",
                "primary_source_id": source_id,
            },
        ),
    ]
