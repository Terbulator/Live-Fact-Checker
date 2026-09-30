import { Link } from 'react-router-dom'
import { ArrowLeft, Clock, Settings } from 'lucide-react'

import LiveCheckerApp from '../components/LiveCheckerApp'

export function DashboardPage() {
  return (
    <div className="dashboard-page">
      <div className="dashboard-bar">
        <div className="dashboard-bar__inner">
          <Link to="/" className="dashboard-bar__back">
            <ArrowLeft size={16} aria-hidden="true" />
            <span>Back to site</span>
          </Link>
          <span className="dashboard-bar__title">Live Fact-Checker</span>
          <nav className="dashboard-bar__links" aria-label="Dashboard">
            <span className="dashboard-bar__pending" title="Not implemented yet">
              <Clock size={15} aria-hidden="true" />
              <span>Session history</span>
              <span className="dashboard-bar__badge">COMING SOON</span>
            </span>
            <span className="dashboard-bar__pending" title="Not implemented yet">
              <Settings size={15} aria-hidden="true" />
              <span>Settings</span>
              <span className="dashboard-bar__badge">COMING SOON</span>
            </span>
          </nav>
        </div>
      </div>

      <LiveCheckerApp />
    </div>
  )
}
