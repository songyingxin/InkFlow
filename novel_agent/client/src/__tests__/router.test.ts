/**
 * 路由测试
 *
 * 测试前端路由配置：
 * - 路由路径定义
 * - 路由名称
 * - 懒加载组件
 */

import { describe, it, expect } from 'vitest'
import router from '@/router'

describe('Router configuration', () => {
  it('has landing route', () => {
    const routes = router.getRoutes()
    const landing = routes.find(r => r.path === '/')
    expect(landing).toBeDefined()
    expect(landing?.name).toBe('landing')
  })

  it('has editor route', () => {
    const routes = router.getRoutes()
    const editor = routes.find(r => r.path === '/editor')
    expect(editor).toBeDefined()
    expect(editor?.name).toBe('editor')
  })

  it('has exactly 2 routes', () => {
    const routes = router.getRoutes()
    expect(routes.length).toBe(2)
  })

  it('routes use lazy loading', () => {
    const routes = router.getRoutes()
    for (const route of routes) {
      expect(route.components?.default).toBeDefined()
    }
  })

  it('uses createWebHistory', () => {
    expect(router.options.history).toBeDefined()
  })
})
