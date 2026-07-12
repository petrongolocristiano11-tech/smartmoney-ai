import { Outlet } from "react-router-dom";

import Navbar from "../components/Navbar";
import NotificationWatcher from "../components/NotificationWatcher";

function MainLayout() {
  return (
    <div className="min-h-screen bg-slate-900">
      <NotificationWatcher />

      <Navbar />

      <Outlet />
    </div>
  );
}

export default MainLayout; 