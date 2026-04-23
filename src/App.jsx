import React from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { useApp } from './context/AppContext';
import { AppLayout } from './components/AppLayout';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { MarketplacePage } from './pages/MarketplacePage';
import { ListingDetailPage } from './pages/ListingDetailPage';
import { InvestorDashboardPage } from './pages/InvestorDashboardPage';
import { ComparePage } from './pages/ComparePage';
import { RequestsPage } from './pages/RequestsPage';
import { SellerListingsPage } from './pages/SellerListingsPage';
import { ListingFormPage } from './pages/ListingFormPage';
import { QuestionsPage } from './pages/QuestionsPage';
import { PipelinePage } from './pages/PipelinePage';
import { CompaniesPage } from './pages/CompaniesPage';
import { UsersPage } from './pages/UsersPage';
import { AdminPage } from './pages/AdminPage';
import { SettingsPage } from './pages/SettingsPage';

function ProtectedRoute({ roles }) {
  const { currentUser } = useApp();
  if (!currentUser) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(currentUser.role)) return <Navigate to="/marketplace" replace />;
  return <Outlet />;
}

function AuthOnly({ children }) {
  const { currentUser } = useApp();
  if (currentUser) return <Navigate to="/marketplace" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthOnly><LoginPage /></AuthOnly>} />
      <Route path="/register" element={<AuthOnly><RegisterPage /></AuthOnly>} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/marketplace" replace />} />
          <Route path="/marketplace" element={<MarketplacePage />} />
          <Route path="/listings/:listingId" element={<ListingDetailPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/settings" element={<SettingsPage />} />

          <Route element={<ProtectedRoute roles={['investor', 'developer']} />}>
            <Route path="/dashboard" element={<InvestorDashboardPage />} />
            <Route path="/compare" element={<ComparePage />} />
          </Route>

          <Route element={<ProtectedRoute roles={['seller', 'broker', 'admin']} />}>
            <Route path="/crm/listings" element={<SellerListingsPage />} />
            <Route path="/crm/listings/new" element={<ListingFormPage />} />
            <Route path="/crm/listings/:listingId/edit" element={<ListingFormPage />} />
            <Route path="/crm/questions" element={<QuestionsPage />} />
            <Route path="/crm/pipeline" element={<PipelinePage />} />
          </Route>

          <Route element={<ProtectedRoute roles={['admin']} />}>
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/admin/companies" element={<CompaniesPage />} />
            <Route path="/admin/users" element={<UsersPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/marketplace" replace />} />
    </Routes>
  );
}
