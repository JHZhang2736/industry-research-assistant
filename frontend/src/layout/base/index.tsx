

import { Footer } from './footer'
import './index.scss'
import { Nav } from './nav'

export function BaseLayout({ children }: { children?: React.ReactNode }) {
  return (
    <div className="base-layout">
      <div className="base-layout__sidebar">
        <div className="base-layout__sidebar-main scrollbar-style">
          <div className="base-layout__brand">
            <div className="base-layout__brand-logo" />
            <span className="base-layout__brand-name">深度研究助手</span>
          </div>

          <Nav />

          <Footer />
        </div>
      </div>

      <div className="base-layout__content">{children}</div>
    </div>
  )
}
