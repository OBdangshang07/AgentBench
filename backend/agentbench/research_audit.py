"""Structural research checks; semantic truth remains a separate obligation."""
from __future__ import annotations


def audit_claim_graph(claims: list) -> dict:
    ids = [item.get('id') for item in claims if isinstance(item, dict)]
    valid_ids = [key for key in ids if isinstance(key, str) and key.strip()]
    errors = []
    if len(valid_ids) != len(claims):
        errors.append('Every claim requires a nonempty string id')
    if len(set(valid_ids)) != len(valid_ids):
        errors.append('Duplicate claim ids')
    known = set(valid_ids)
    graph = {}
    for item in claims:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            continue
        deps = item.get('depends_on')
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            errors.append(f"Invalid depends_on for {item['id']}")
            continue
        if any(d not in known for d in deps):
            errors.append(f"Unknown dependency for {item['id']}")
        graph[item['id']] = set(deps) & known
    # Iterative topological traversal also handles large, legitimate documents.
    reverse = {key: set() for key in known}
    degree = {key: len(graph.get(key, ())) for key in known}
    for key, deps in graph.items():
        for dep in deps:
            reverse[dep].add(key)
    ready = [key for key, count in degree.items() if count == 0]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for dependent in reverse[key]:
            degree[dependent] -= 1
            if degree[dependent] == 0:
                ready.append(dependent)
    if visited != len(known):
        errors.append('Claim dependency graph contains a cycle')
    return {'score': 0.0 if errors else 100.0, 'errors': errors[:20],
            'nodes': len(known), 'edges': sum(map(len, graph.values()))}
