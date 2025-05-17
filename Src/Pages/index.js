import { useState, useEffect } from 'react';
import { initializeParameters, executeTrade, generateSchedule } from '@/lib/trading';

export default function Dashboard() {
  const [prices, setPrices] = useState([]);
  const [historicalPrices, setHistoricalPrices] = useState([]);
  const [capital, setCapital] = useState({
    daily: 2000,
    weekly: 2000,
    biweekly: 2000,
    monthly: 2000,
    quarterly: 2000
  });
  const [trades, setTrades] = useState([]);
  const [schedule, setSchedule] = useState([]);
  const [thresholds, setThresholds] = useState({});
  const [holdings, setHoldings] = useState({
    daily: { units: 0, entryPrice: 0 },
    weekly: { units: 0, entryPrice: 0 },
    biweekly: { units: 0, entryPrice: 0 },
    monthly: { units: 0, entryPrice: 0 },
    quarterly: { units: 0, entryPrice: 0 }
  });
  const [lastTradeDates, setLastTradeDates] = useState({
    daily: '',
    weekly: '',
    biweekly: '',
    monthly: '',
    quarterly: ''
  });
  const [getBalance, setGetBalance] = useState(0);

  const fetchHistoricalPrices = async () => {
    const res = await fetch('/api/coin-prices?historical=true');
    const data = await res.json();
    if (data.success) {
      setHistoricalPrices(data.prices);
      const newThresholds = initializeParameters(data.prices);
      setThresholds(newThresholds);
      const tradeSchedule = generateSchedule(data.prices, newThresholds);
      setSchedule(tradeSchedule);
      console.log('Trade Schedule:', tradeSchedule);
    }
  };

  const fetchPrices = async () => {
    const res = await fetch('/api/coin-prices');
    const data = await res.json();
    if (data.success) {
      setPrices((prev) => {
        const newPrices = [...prev, ...data.prices].slice(-100);
        const btcPrices = newPrices.filter((p) => p.id === 'bitcoin');
        if (btcPrices.length >= 90) {
          const currentPrice = btcPrices[btcPrices.length - 1].current_price;
          const prevPrices = {
            daily: btcPrices[btcPrices.length - 2]?.current_price,
            weekly: btcPrices[btcPrices.length - 7]?.current_price,
            biweekly: btcPrices[btcPrices.length - 14]?.current_price,
            monthly: btcPrices[btcPrices.length - 30]?.current_price,
            quarterly: btcPrices[btcPrices.length - 90]?.current_price
          };
          const { actions, newCapital, newHoldings, newLastTradeDates } = executeTrade(
            currentPrice,
            prevPrices,
            thresholds,
            capital,
            holdings,
            lastTradeDates
          );
          if (actions.length) {
            console.log('Trades Executed:', actions);
            setTrades((prev) => [...prev, ...actions.map((a, i) => ({ id: prev.length + i + 1, ...a }))].slice(-50));
            setCapital(newCapital);
            setHoldings(newHoldings);
            setLastTradeDates(newLastTradeDates);
          }
        }
        return newPrices;
      });
    }
  };

  const mintGet = async () => {
    const res = await fetch('/api/mint-get', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: 'randall', joules: 100 }),
    });
    const data = await res.json();
    if (data.success) setGetBalance(getBalance + data.gets);
  };

  useEffect(() => {
    fetchHistoricalPrices();
    fetchPrices();
    const interval = setInterval(fetchPrices, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Midas-x MVP Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-gray-100 p-4 rounded">
          <h2 className="text-xl mb-2">Crypto Prices (Yahoo Finance)</h2>
          <ul>
            {prices.slice(-2).map((coin) => (
              <li key={coin.id} className="mb-1">
                {coin.name}: ${coin.current_price} ({coin.price_change_percentage_24h.toFixed(2)}% 24h)
              </li>
            ))}
          </ul>
        </div>
        <div className="bg-gray-100 p-4 rounded">
          <h2 className="text-xl mb-2">GET Balance</h2>
          <p>{getBalance} GET ($10/GET = ${getBalance * 10})</p>
          <button
            onClick={mintGet}
            className="mt-2 bg-blue-500 text-white p-2 rounded hover:bg-blue-600"
          >
            Mint GET (100 J)
          </button>
        </div>
        <div className="bg-gray-100 p-4 rounded col-span-1 md:col-span-2">
          <h2 className="text-xl mb-2">Trades (1,000x ROI Potential)</h2>
          <p>Total Capital: ${(Object.values(capital).reduce((sum, c) => sum + c, 0)).toFixed(2)}</p>
          <ul className="max-h-64 overflow-y-auto">
            {trades.map((trade) => (
              <li key={trade.id} className="mb-1">
                {trade.timeframe.toUpperCase()} {trade.type} @ ${trade.price.toFixed(2)}{' '}
                {trade.profit ? `(Profit: $${trade.profit.toFixed(2)})` : `(${trade.units.toFixed(4)} units)`}
              </li>
            ))}
          </ul>
        </div>
        <div className="bg-gray-100 p-4 rounded col-span-1 md:col-span-2">
          <h2 className="text-xl mb-2">Trade Schedule (Next 7 Days)</h2>
          <ul className="max-h-64 overflow-y-auto">
            {schedule.map((entry, index) => (
              <li key={index} className="mb-1">
                {entry.date}: {Object.entries(entry.trades).map(([tf, t]) => (
                  `${tf.toUpperCase()}: ${t.action} at ${(t.threshold * 100).toFixed(1)}% dip (~$${t.estimatedPrice.toFixed(0)}) `
                )).join(', ')}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
                        }
