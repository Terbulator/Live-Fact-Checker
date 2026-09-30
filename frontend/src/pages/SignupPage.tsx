import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Mail, Lock, User, Eye, EyeOff, Info } from 'lucide-react'

export function SignupPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  return (
    <div className="auth-page">
      <div className="auth-glow" aria-hidden="true" />
      <motion.div
        className="auth-container"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.2, 0.7, 0.3, 1] }}
      >
        <div className="auth-header">
          <Link to="/" className="auth-logo" aria-label="Live Fact-Checker home">
            <span className="auth-logo-mark" aria-hidden="true" />
            <span>LIVE FACT-CHECKER</span>
          </Link>
        </div>

        <motion.div
          className="auth-card"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1, ease: [0.2, 0.7, 0.3, 1] }}
        >
          <div className="auth-title-group">
            <h1 className="auth-title">Create an account</h1>
            <p className="auth-subtitle">Account creation is not available yet.</p>
          </div>

          <div className="auth-notice" role="status">
            <Info size={18} aria-hidden="true" />
            <div>
              <strong>Accounts are not implemented.</strong>
              <p>
                There is no authentication service behind this form, so nothing is submitted
                and no details are stored. The fact-checker itself is open right now.
              </p>
            </div>
          </div>

          <form className="auth-form" onSubmit={(event) => event.preventDefault()} noValidate>
            <div className="auth-field">
              <label htmlFor="signup-name" className="auth-label">
                Name
              </label>
              <div className="auth-input-wrapper">
                <User className="auth-input-icon" size={18} aria-hidden="true" />
                <input
                  type="text"
                  id="signup-name"
                  name="name"
                  className="auth-input"
                  placeholder="Your name"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  disabled
                />
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="signup-email" className="auth-label">
                Email
              </label>
              <div className="auth-input-wrapper">
                <Mail className="auth-input-icon" size={18} aria-hidden="true" />
                <input
                  type="email"
                  id="signup-email"
                  name="email"
                  className="auth-input"
                  placeholder="you@example.com"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled
                />
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="signup-password" className="auth-label">
                Password
              </label>
              <div className="auth-input-wrapper">
                <Lock className="auth-input-icon" size={18} aria-hidden="true" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="signup-password"
                  name="password"
                  className="auth-input"
                  placeholder="••••••••"
                  autoComplete="new-password"
                  disabled
                />
                <button
                  type="button"
                  className="auth-password-toggle"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  disabled
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button type="submit" className="button button--primary button--lg button--full" disabled>
              Create account
            </button>
          </form>

          <Link to="/dashboard" className="button button--secondary button--lg button--full auth-alt">
            Open the fact-checker instead
          </Link>

          <p className="auth-footer">
            Already have an account? <Link to="/login" className="auth-link">Log in</Link>
          </p>
        </motion.div>
      </motion.div>
    </div>
  )
}
