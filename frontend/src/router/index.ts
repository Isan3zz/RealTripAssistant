import { createRouter, createWebHistory } from 'vue-router'
import TripList from '@/views/TripList.vue'
import TripDetail from '@/views/TripDetail.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: TripList },
    { path: '/trips/:id', name: 'trip-detail', component: TripDetail },
  ],
})

export default router
