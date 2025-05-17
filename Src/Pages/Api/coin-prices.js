import axios from 'axios';

export default async function handler(req, res) {
  if (req.method === 'GET') {
    const { historical } = req.query;
    try {
      if (historical) {
        // Mock 3 months of daily Bitcoin prices (Jan 26, 2025 - April 26, 2025)
        const mockHistorical = Array.from({ length: 90 }, (_, i) => {
          const date = new Date('2025-01-26');
          date.setDate(date.getDate() + i);
          return {
            id: 'bitcoin',
            current_price: 60000 + Math.random() * 5000 - 2500, // Simulate $57.5K-$62.5K range
            last_updated: date.toISOString()
          };
        });
        res.status(200).json({ success: true, prices: mockHistorical });
      } else {
        const response = await axios.get('https://api.coingecko.com/api/v3/coins/markets', {
          params: {
            vs_currency: 'usd',
            ids: 'bitcoin,ethereum',
            x_cg_demo_api_key: process.env.COINGECKO_API_KEY,
          },
        });
        res.status(200).json({ success: true, prices: response.data });
      }
    } catch (error) {
      res.status(500).json({ error: 'Failed to fetch prices' });
    }
  } else {
    res.status(405).json({ error: 'Method not allowed' });
  }
}
