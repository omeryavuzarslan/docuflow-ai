import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

import { api } from "./api/client";
import { Sidebar } from "./components/Sidebar";
import { ComingSoon } from "./pages/ComingSoon";
import { DocumentPage } from "./pages/DocumentPage";
import { DocumentsPage } from "./pages/DocumentsPage";

export default function App() {
  const openFindings = useQuery({
    queryKey: ["discrepancies", "open"],
    queryFn: async () => (await api.GET("/discrepancies", { params: { query: { status: "open" } } })).data ?? [],
  });

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar openFindings={openFindings.data?.length} />
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:id" element={<DocumentPage />} />
          <Route
            path="/findings"
            element={<ComingSoon title="Findings" description="Every discrepancy in one inbox, with resolve and dismiss, arrives in 8c." />}
          />
          <Route
            path="/ask"
            element={<ComingSoon title="Ask" description="Questions answered from your documents, with citations, arrive in 8d." />}
          />
        </Routes>
      </main>
    </div>
  );
}
