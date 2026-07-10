from collections import defaultdict

from backend.app.models.wallet_edge import WalletEdge


def get_wallet_clusters(db, min_connections: int = 2):
    edges = db.query(WalletEdge).all()

    graph = defaultdict(set)

    for edge in edges:
        graph[edge.source_wallet].add(edge.target_wallet)
        graph[edge.target_wallet].add(edge.source_wallet)

    clusters = []

    visited = set()

    for wallet in graph:

        if wallet in visited:
            continue

        stack = [wallet]
        cluster = set()

        while stack:
            current = stack.pop()

            if current in visited:
                continue

            visited.add(current)
            cluster.add(current)

            for neighbor in graph[current]:
                if neighbor not in visited:
                    stack.append(neighbor)

        if len(cluster) >= min_connections:
            clusters.append(
                {
                    "wallets": sorted(cluster),
                    "size": len(cluster),
                }
            )

    clusters.sort(
        key=lambda item: item["size"],
        reverse=True,
    )

    return {
        "clusters": clusters,
        "count": len(clusters),
    } 