import { Outlet } from "react-router-dom";

import Navbar from "../components/Navbar";

function MainLayout() {
  return (
    <div className="min-h-screen bg-slate-900">
      <Navbar />
      <Outlet />
    </div>
  );
}

export default MainLayout; 