import { ThemeProvider } from "./contexts/theme-provider"
import { SidebarProvider } from "./components/ui/sidebar"
import { DashboardSidebar } from "./components/DashboardSidebar"
import { RfDataProvider } from "./contexts/rf-data"
import { BrowserRouter, Routes, Route } from "react-router-dom";
import RFMetricsPage from "./pages/RFMetricsPage";

export default function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="theme">
      <SidebarProvider>
        <RfDataProvider>
          <DashboardSidebar />
          <div className="flex flex-1 flex-col">
            <BrowserRouter>
              <Routes>
                <Route path="/" element={<RFMetricsPage />} />
              </Routes>
            </BrowserRouter>
          </div>
        </RfDataProvider>
      </SidebarProvider>
    </ThemeProvider>
  )
}