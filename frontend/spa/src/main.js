import { createApp } from 'vue'
import App from './App.vue'
import router from './router/index.js'
import './shared/styles/main.css'
import './modules/posts/styles/main.css'

createApp(App).use(router).mount('#app')
