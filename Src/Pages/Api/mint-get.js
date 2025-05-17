import { Connection, Keypair } from '@solana/web3.js';

export default async function handler(req, res) {
  if (req.method === 'POST') {
    const { user, joules } = req.body;
    if (joules >= 100) {
      const gets = joules / 100;
      const connection = new Connection('https://api.devnet.solana.com');
      const keypair = Keypair.generate();
      res.status(200).json({ success: true, gets, value: gets * 10, mint: keypair.publicKey.toString() });
    } else {
      res.status(400).json({ error: 'Need 100 J' });
    }
  } else {
    res.status(405).json({ error: 'Method not allowed' });
  }
}
