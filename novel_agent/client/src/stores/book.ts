import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Book } from '@/types'
import * as api from '@/api'

export const useBookStore = defineStore('book', () => {
  const books = ref<Book[]>([])
  const loading = ref(false)
  const error = ref('')

  async function fetchBooks() {
    loading.value = true
    error.value = ''
    try {
      const data = await api.listBooks()
      books.value = data.books || []
    } catch (e: any) {
      error.value = e.message || '加载失败'
    } finally {
      loading.value = false
    }
  }

  async function createBook(title: string) {
    const data = await api.createBook(title)
    return data
  }

  async function selectBook(name: string) {
    const data = await api.selectBook(name)
    return data
  }

  async function deleteBook(name: string) {
    const data = await api.deleteBook(name)
    books.value = data.books || []
    return data
  }

  return { books, loading, error, fetchBooks, createBook, selectBook, deleteBook }
})
