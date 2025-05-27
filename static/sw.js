// static/sw.js

const CACHE_NAME = 'qr-manager-cache-v1';
const URLS_TO_CACHE = [
  '/', // Cache trang chủ
  '/static/style.css', // Cache file CSS chính
  // Thêm các đường dẫn đến các file tĩnh quan trọng khác nếu cần
  // Ví dụ: '/static/landing-style.css', '/static/some-image.png'
];

// Sự kiện install: được gọi khi service worker được cài đặt
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Opened cache');
        return cache.addAll(URLS_TO_CACHE);
      })
  );
});

// Sự kiện fetch: được gọi mỗi khi có một yêu cầu mạng từ ứng dụng
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Nếu tìm thấy trong cache, trả về từ cache
        if (response) {
          return response;
        }
        // Nếu không, thực hiện yêu cầu mạng thực sự
        return fetch(event.request);
      })
  );
});