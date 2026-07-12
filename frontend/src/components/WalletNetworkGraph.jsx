import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
} from "reactflow";

import "reactflow/dist/style.css";

function shortenAddress(address, start = 6, end = 5) {
  if (!address) return "-";

  if (address.length <= start + end + 3) {
    return address;
  }

  return `${address.slice(0, start)}...${address.slice(-end)}`;
}

function WalletNetworkGraph({
  walletAddress,
  connectedWallets = [],
}) {
  const navigate = useNavigate();

  const { nodes, edges } = useMemo(() => {
    if (!walletAddress) {
      return {
        nodes: [],
        edges: [],
      };
    }

    const centerX = 400;
    const centerY = 250;
    const radius = 220;

    const graphNodes = [
      {
        id: walletAddress,
        position: {
          x: centerX,
          y: centerY,
        },
        data: {
          label: `Main\n${shortenAddress(walletAddress)}`,
          wallet: walletAddress,
          isMain: true,
        },
        style: {
          width: 150,
          padding: 12,
          borderRadius: 12,
          border: "2px solid #3b82f6",
          background: "#1e3a8a",
          color: "#dbeafe",
          fontWeight: 700,
          textAlign: "center",
          whiteSpace: "pre-line",
        },
      },
    ];

    const graphEdges = [];

    connectedWallets.forEach((item, index) => {
      const wallet = item.wallet;

      if (!wallet) {
        return;
      }

      const angle =
        (index / Math.max(connectedWallets.length, 1)) *
        Math.PI *
        2;

      const x = centerX + Math.cos(angle) * radius;
      const y = centerY + Math.sin(angle) * radius;

      graphNodes.push({
        id: wallet,
        position: {
          x,
          y,
        },
        data: {
          label: `${shortenAddress(wallet)}\nScore ${
            item.smart_score ?? 0
          }`,
          wallet,
          isMain: false,
        },
        style: {
          width: 145,
          padding: 10,
          borderRadius: 12,
          border: "1px solid #7c3aed",
          background: "#312e81",
          color: "#ede9fe",
          textAlign: "center",
          whiteSpace: "pre-line",
          cursor: "pointer",
        },
      });

      graphEdges.push({
        id: `${walletAddress}-${wallet}`,
        source: walletAddress,
        target: wallet,
        label: `${item.shared_tokens ?? 0} token`,
        animated:
          Number(item.connection_strength ?? 0) >= 50,
        style: {
          strokeWidth: Math.max(
            1,
            Math.min(
              5,
              Number(item.connection_strength ?? 1) / 20
            )
          ),
        },
        labelStyle: {
          fill: "#cbd5e1",
          fontSize: 11,
        },
      });
    });

    return {
      nodes: graphNodes,
      edges: graphEdges,
    };
  }, [walletAddress, connectedWallets]);

  function handleNodeClick(_, node) {
    const selectedWallet = node.data?.wallet;

    if (
      selectedWallet &&
      selectedWallet !== walletAddress
    ) {
      navigate(`/wallet/${selectedWallet}`);
    }
  }

  return (
    <section className="mb-8 overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
      <div className="border-b border-slate-700 p-5">
        <h2 className="text-xl font-bold">
          Wallet Network Graph
        </h2>

        <p className="mt-1 text-sm text-slate-400">
          Relazioni tra il wallet principale e i wallet
          collegati. Clicca un nodo per aprirlo.
        </p>
      </div>

      {connectedWallets.length === 0 ? (
        <div className="flex h-96 items-center justify-center text-slate-400">
          Nessuna connessione disponibile.
        </div>
      ) : (
        <div className="h-[520px] w-full">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodeClick={handleNodeClick}
            fitView
            fitViewOptions={{
              padding: 0.2,
            }}
            nodesDraggable
            nodesConnectable={false}
            elementsSelectable
            proOptions={{
              hideAttribution: true,
            }}
          >
            <Background gap={22} size={1} />
            <MiniMap zoomable pannable />
            <Controls />
          </ReactFlow>
        </div>
      )}
    </section>
  );
}

export default WalletNetworkGraph; 