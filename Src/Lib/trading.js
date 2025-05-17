// src/lib/trading.js
export const executeTrade = (currentPrices, prevPrices, thresholds, capital, holdings, lastTradeDates, getBalance) => {
    const actions = [];
    const newCapital = { ...capital };
    const newHoldings = { ...holdings };
    const newLastTradeDates = { ...lastTradeDates };
    const today = new Date().toISOString().split('T')[0];
    const markets = { small: ['SHIB-USD', 'DOGS-USD'], large: ['BTC-USD', 'ETH-USD'] };
    const REALLOC_ALLOCATION = 0.3, REALLOC_GAIN = 0.1;
    const cascadeRatios = {
        small: { daily: { true: 0.8, false: 0.7 }, weekly: { true: 0.6, false: 0.5 } },
        large: { daily: { true: 0.7, false: 0.6 }, weekly: { true: 0.5, false: 0.4 } }
    };
    const trailingStop = 0.05, stopLoss = 0.10;
    const layerBuyThresholds = {
        main: [0.008, 0.004, 0.002, 0.001],
        nano: [0.0008, 0.0004, 0.0002, 0.0001],
        pico: [0.000015, 0.000025, 0.00004, 0.00008]
    };
    const layerSellTriggers = {
        main: [0.4, 0.5, 0.6, 0.8],
        nano: [0.5, 0.6, 0.7, 0.9],
        pico: [0.6, 0.7, 0.8, 1.0]
    };
    const incrementalBuyThresholds = [0.02, 0.04, 0.06]; // 2%, 4%, 6% dips
    const sellChangeTrigger = 0.07; // 7% sell trigger

    const detectTopRiser = () => {
        const changes = {};
        for (const ticker of [...markets.small, ...markets.large]) {
            const price = currentPrices[ticker]?.current_price || prevPrices[ticker];
            const prevPrice = prevPrices[ticker] || price;
            changes[ticker] = (price - prevPrice) / prevPrice;
        }
        const topRiser = Object.keys(changes).reduce((a, b) => changes[a] > changes[b] ? a : b, 'SHIB-USD');
        return { topRiser, isValid: changes[topRiser] > 0 };
    };

    const { topRiser, isValid: isTopRiserValid } = detectTopRiser();

    for (const marketType of ['small', 'large']) {
        for (const ticker of markets[marketType]) {
            for (const timeframe of ['daily', 'weekly']) {
                const lastTradeDate = newLastTradeDates[`${ticker}_${timeframe}`] || '1970-01-01';
                const days = timeframe === 'daily' ? 1 : 7;
                const daysSinceLastTrade = (new Date(today) - new Date(lastTradeDate)) / (1000 * 60 * 60 * 24);
                if (daysSinceLastTrade < days) continue;

                const currentPrice = currentPrices[ticker]?.current_price || prevPrices[ticker];
                const prevPrice = prevPrices[`${ticker}_${timeframe}`] || currentPrice;
                const holding = newHoldings[`${ticker}_${timeframe}`] || { units: 0, entryPrice: 0, realloc: false };
                const tfThresholds = thresholds[`${ticker}_${timeframe}`];
                const latestMA20 = tfThresholds.longMA[tfThresholds.longMA.length - 1] || currentPrice;
                const latestRSI = tfThresholds.rsi[tfThresholds.rsi.length - 1] || 50;
                const highVol = tfThresholds.volatility[tfThresholds.volatility.length - 1] > 0.15;

                for (const layer of ['main', 'nano', 'pico']) {
                    const buyThreshold = layerBuyThresholds[layer][0];
                    const sellTrigger = layerSellTriggers[layer][0];
                    const baseTradeSize = (marketType === 'small' ? (highVol ? 5 : 3) : (highVol ? 20 : 15)) / 3;

                    if (!holding.units) {
                        let signal = 0;
                        if (latestRSI < 25 && currentPrice <= latestMA20 * (1 - buyThreshold)) {
                            signal = 1;
                        }
                        for (let j = 0; j < incrementalBuyThresholds.length; j++) {
                            if (latestRSI < 25 && currentPrice <= latestMA20 * (1 - incrementalBuyThresholds[j])) {
                                signal = j + 2;
                            }
                        }
                        const priceChange = (currentPrice - prevPrice) / prevPrice;
                        const isRealloc = priceChange < -0.01 && isTopRiserValid && topRiser !== ticker && !holding.realloc;
                        let tradeSize = baseTradeSize * (signal >= 6 ? 2 : 1);
                        if (isRealloc) tradeSize *= REALLOC_ALLOCATION;

                        if (signal >= 1 || isRealloc) {
                            const units = tradeSize / currentPrice;
                            actions.push({ ticker, timeframe, layer, type: 'BUY', price: currentPrice, units, realloc: isRealloc });
                            newCapital[`${ticker}_${timeframe}`] -= units * currentPrice;
                            newHoldings[`${ticker}_${timeframe}`] = { units, entryPrice: currentPrice, realloc: isRealloc };
                            newLastTradeDates[`${ticker}_${timeframe}`] = today;
                            console.log(`${ticker} ${timeframe} ${layer} BUY: ${units} units @ ${currentPrice} (Signal: ${signal}, Realloc: ${isRealloc})`);
                        }
                    } else {
                        const isSpike = currentPrice >= holding.entryPrice * (1 + sellTrigger);
                        const isChangeSell = currentPrice >= prevPrice * (1 + sellChangeTrigger);
                        const isTrailingStop = currentPrice <= prevPrice * (1 - trailingStop);
                        const isStopLoss = currentPrice <= holding.entryPrice * (1 - stopLoss);
                        const isReallocSell = holding.realloc && currentPrice >= holding.entryPrice * (1 + REALLOC_GAIN);
                        if (isSpike || isChangeSell || isTrailingStop || isStopLoss || isReallocSell) {
                            const profit = (currentPrice - holding.entryPrice) * holding.units;
                            const cascadeProfit = profit * cascadeRatios[marketType][timeframe][highVol];
                            actions.push({ ticker, timeframe, layer, type: 'SELL', price: currentPrice, profit: cascadeProfit, realloc: holding.realloc });
                            newCapital[`${ticker}_${timeframe}`] += holding.units * currentPrice;
                            newHoldings[`${ticker}_${timeframe}`] = { units: 0, entryPrice: 0, realloc: false };
                            newLastTradeDates[`${ticker}_${timeframe}`] = today;
                            newCapital[`${topRiser}_${timeframe}`] += cascadeProfit * 0.3;
                            console.log(`${ticker} ${timeframe} ${layer} SELL: Profit $${cascadeProfit} (Spike: ${isSpike}, Change: ${isChangeSell}, TrailingStop: ${isTrailingStop}, StopLoss: ${isStopLoss}, Realloc: ${isReallocSell})`);
                        }
                    }
                }
            }
        }
    }
    const getsMinted = actions.reduce((sum, a) => sum + (a.type === 'SELL' ? Math.floor(a.price * a.units / 1000) : 0), 0);
    return { actions, newCapital, newHoldings, newLastTradeDates, getsUsed: 0, getsMinted };
};
