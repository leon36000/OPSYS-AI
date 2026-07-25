// Smoke test k6 (pas un test de charge).
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: 5,
  duration: '10s',
  thresholds: {
    http_req_failed: ['rate==0'],      // loopback : aucun échec toléré
    http_req_duration: ['p(95)<500'],  // 95e percentile < 500 ms
  },
};

export default function () {
  const baseUrl = __ENV.BASE_URL || 'http://127.0.0.1:8080';
  const res = http.get(`${baseUrl}/brand`);
  check(res, {
    'status is 200': (r) => r.status === 200,
    'content-type is json': (r) => {
      const ct = r.headers['Content-Type'] || '';
      return ct.includes('application/json');
    },
  });
}
