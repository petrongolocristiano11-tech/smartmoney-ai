import {
  lazy,
  StrictMode,
  Suspense,
} from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Route,
  Routes,
} from "react-router-dom";

import "./index.css";

import MainLayout from "./layouts/MainLayout.jsx";

const App = lazy(() => import("./App.jsx"));

const Alerts = lazy(() =>
  import("./pages/Alerts.jsx")
);

const Discovery = lazy(() =>
  import("./pages/Discovery.jsx")
);

const LiveScanner = lazy(() =>
  import("./pages/LiveScanner.jsx")
);

const Signals = lazy(() =>
  import("./pages/Signals.jsx")
);

const TokenDetails = lazy(() =>
  import("./pages/TokenDetails.jsx")
);

const WalletDetails = lazy(() =>
  import("./pages/WalletDetails.jsx")
);

const Watchlist = lazy(() =>
  import("./pages/Watchlist.jsx")
);

function PageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 text-white">
      <div className="text-center">
        <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

        <p className="mt-4 text-slate-400">
          Caricamento pagina...
        </p>
      </div>
    </div>
  );
}

createRoot(
  document.getElementById("root")
).render(
  <StrictMode>
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<App />} />

            <Route
              path="/live"
              element={<LiveScanner />}
            />

            <Route
              path="/discovery"
              element={<Discovery />}
            />

            <Route
              path="/signals"
              element={<Signals />}
            />

            <Route
              path="/alerts"
              element={<Alerts />}
            />

            <Route
              path="/watchlist"
              element={<Watchlist />}
            />

            <Route
              path="/wallet/:walletAddress"
              element={<WalletDetails />}
            />

            <Route
              path="/token/:tokenMint"
              element={<TokenDetails />}
            />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  </StrictMode>
); 