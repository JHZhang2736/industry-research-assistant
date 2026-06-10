import IconHistory from '@/assets/layout/history.svg'
import IconHome from '@/assets/layout/home.svg'
import IconNewChat from '@/assets/layout/newchat.svg'
import { SessionDrawer } from '@/components/session-drawer'
import { useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { NavItem } from './nav-item'
import './nav.scss'

export function Nav() {
  const { pathname } = useLocation()
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false)

  const items = useMemo(
    () => [
      {
        key: 'home',
        label: '首页',
        icon: IconHome,
        href: '/',
      },
      {
        key: 'newchat',
        label: '新的聊天',
        icon: IconNewChat,
        href: '/chat',
      },
      {
        key: 'history',
        label: '对话历史',
        icon: IconHistory,
        href: '#',
        onClick: () => setSessionDrawerOpen(true),
      },
    ],
    [],
  )

  return (
    <>
      <div className="base-layout-nav">
        <div className="base-layout-nav__label">导航</div>
        {items.map(({ key, onClick, ...item }) => (
          <NavItem
            key={key}
            {...item}
            active={pathname === item.href}
            onClick={onClick}
          />
        ))}
      </div>
      <SessionDrawer
        open={sessionDrawerOpen}
        onClose={() => setSessionDrawerOpen(false)}
      />
    </>
  )
}
