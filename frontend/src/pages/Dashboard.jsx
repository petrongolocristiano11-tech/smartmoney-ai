import { useQuery } from "@tanstack/react-query";
import { getDashboard } from "../api/dashboard";

export default function Dashboard() {
    const { data, isLoading, error } = useQuery({
        queryKey: ["dashboard"],
        queryFn: getDashboard,
        refetchInterval: 10000,
    });

    if (isLoading) {
        return (
            <div className="p-8 text-white">
                Loading Dashboard...
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-8 text-red-500">
                Backend offline
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-zinc-950 text-white p-8">

            <h1 className="text-4xl font-bold mb-8">
                SmartMoney AI
            </h1>

            <pre className="bg-zinc-900 p-4 rounded-xl overflow-auto">
                {JSON.stringify(data, null, 2)}
            </pre>

        </div>
    );
} 