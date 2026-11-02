function getPercentile(sortedArr, percentile) {
  if (!sortedArr.length) return 0;
  const index = (percentile / 100) * (sortedArr.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sortedArr[lower];
  const weight = index - lower;
  return sortedArr[lower] * (1 - weight) + sortedArr[upper] * weight;
}

self.onmessage = function (e) {
  const {
    history,
    currentInrPrice,
    targetDropPct,
    dropTolerance,
    targetFng,
    fngTolerance,
  } = e.data;

  const FORWARD_DAYS = 60;
  const MIN_GAP_DAYS = 14;
  const MS_PER_DAY = 86400000;

  const matches = [];
  let lastMatchedDateMs = -Infinity;

  // Exclude the most recent 60 rows because they do not yet have a full 60-day forward outcome
  for (let i = 0; i < history.length - FORWARD_DAYS; i++) {
    const row = history[i];
    if (row.drop_30d_pct === null || row.drop_30d_pct === undefined) continue;

    const dropDiff = Math.abs(row.drop_30d_pct - targetDropPct);
    const fngDiff = Math.abs(row.fng - targetFng);

    if (dropDiff <= dropTolerance && fngDiff <= fngTolerance) {
      const currentDateMs = Date.parse(row.date);
      if ((currentDateMs - lastMatchedDateMs) / MS_PER_DAY >= MIN_GAP_DAYS) {
        lastMatchedDateMs = currentDateMs;

        const basePrice = row.close_inr;
        const forwardPctCurve = [];
        let maxExtraDipPct = 0;

        for (let d = 0; d <= FORWARD_DAYS; d++) {
          const futurePrice = history[i + d].close_inr;
          const pctChange = ((futurePrice - basePrice) / basePrice) * 100;
          forwardPctCurve.push(pctChange);
          if (pctChange < maxExtraDipPct) {
            maxExtraDipPct = pctChange;
          }
        }

        matches.push({
          date: row.date,
          entryInr: basePrice,
          drop30d: row.drop_30d_pct,
          fng: row.fng,
          day60ReturnPct: forwardPctCurve[FORWARD_DAYS],
          maxExtraDipPct: maxExtraDipPct,
          forwardPctCurve: forwardPctCurve,
        });
      }
    }
  }

  if (matches.length === 0) {
    self.postMessage({ matchCount: 0 });
    return;
  }

  const labels = [];
  const p10Pct = [];
  const p50Pct = [];
  const p90Pct = [];
  const p10Inr = [];
  const p50Inr = [];
  const p90Inr = [];

  for (let d = 0; d <= FORWARD_DAYS; d++) {
    labels.push(`Day ${d}`);
    const dayReturns = matches
      .map((m) => m.forwardPctCurve[d])
      .sort((a, b) => a - b);

    const val10 = getPercentile(dayReturns, 10);
    const val50 = getPercentile(dayReturns, 50);
    const val90 = getPercentile(dayReturns, 90);

    p10Pct.push(Number(val10.toFixed(2)));
    p50Pct.push(Number(val50.toFixed(2)));
    p90Pct.push(Number(val90.toFixed(2)));

    p10Inr.push(Math.round(currentInrPrice * (1 + val10 / 100)));
    p50Inr.push(Math.round(currentInrPrice * (1 + val50 / 100)));
    p90Inr.push(Math.round(currentInrPrice * (1 + val90 / 100)));
  }

  const positiveMatches = matches.filter((m) => m.day60ReturnPct > 0).length;
  const winRatePct = Number(((positiveMatches / matches.length) * 100).toFixed(1));

  const day60Sorted = matches.map((m) => m.day60ReturnPct).sort((a, b) => a - b);
  const typicalReturnPct = Number(getPercentile(day60Sorted, 50).toFixed(2));
  const typicalProjectedInr = Math.round(
    currentInrPrice * (1 + typicalReturnPct / 100)
  );
  const typicalDeltaInr = typicalProjectedInr - Math.round(currentInrPrice);

  const extraDipsSorted = matches.map((m) => m.maxExtraDipPct).sort((a, b) => a - b);
  const typicalExtraDipPct = Number(getPercentile(extraDipsSorted, 50).toFixed(2));
  const typicalExtraDipFloorInr = Math.round(
    currentInrPrice * (1 + typicalExtraDipPct / 100)
  );
  const typicalExtraDipDeltaInr =
    typicalExtraDipFloorInr - Math.round(currentInrPrice);

  self.postMessage({
    matchCount: matches.length,
    winRatePct,
    typicalReturnPct,
    typicalProjectedInr,
    typicalDeltaInr,
    typicalExtraDipPct,
    typicalExtraDipFloorInr,
    typicalExtraDipDeltaInr,
    labels,
    p10Pct,
    p50Pct,
    p90Pct,
    p10Inr,
    p50Inr,
    p90Inr,
    matches: matches.slice(-10).reverse(),
  });
};