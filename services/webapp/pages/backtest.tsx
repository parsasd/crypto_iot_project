import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';

interface BacktestResult {
  pnl: number;
  win_rate: number;
  max_drawdown: number;
  sharpe: number;
  equity_curve: number[];
  dates: string[];
  trades: any[];
}

interface ExampleItem {
  timestamp: string;
  signal: number;
  chart_url: string;
  outcome_pct: number | null;
}

export default function Backtest() {
  const router = useRouter();
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState('');
  const [logic, setLogic] = useState('and');
  const [signals, setSignals] = useState<{ [key: string]: boolean }>({ macd_cross: true, bollinger: true });
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [examples, setExamples] = useState<ExampleItem[]>([]);
  const [message, setMessage] = useState('');

  useEffect(() => {
    async function init() {
      const me = await fetch('/api/me');
      if (me.status === 401) {
        router.push('/');
        return;
      }
      const wlRes = await fetch('/api/watchlist');
      const wl = await wlRes.json();
      setSymbols(wl.symbols || []);
    }
    init();
  }, [router]);

  const runBacktest = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    setResult(null);
    setExamples([]);
    const selectedSignals = Object.entries(signals)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (!symbol || selectedSignals.length === 0) {
      setMessage('Select symbol and at least one signal');
      return;
    }
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - 18); // last 18 months
    const body = {
      symbol,
      interval: '4h',
      start: start.toISOString(),
      end: end.toISOString(),
      rule: { logic, signals: selectedSignals },
      initial_capital: 10000,
      fee_pct: 0.0005,
    };
    try {
      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (res.ok) {
        setResult(data);
        // fetch examples
        const exRes = await fetch('/api/backtest-examples', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, num_examples: 3 }),
        });
        const exData = await exRes.json();
        if (exRes.ok) {
          setExamples(exData.examples);
        }
      } else {
        setMessage(data.message || 'Backtest error');
      }
    } catch (err) {
      setMessage('Request failed');
    }
  };
  return (
    <div style={{ maxWidth: '800px', margin: '2rem auto', fontFamily: 'sans-serif' }}>
      <h1>Backtest</h1>
      <form onSubmit={runBacktest}>
        <label>Symbol:&nbsp;
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">Select symbol</option>
            {symbols.map((sym) => (
              <option key={sym} value={sym}>{sym}</option>
            ))}
          </select>
        </label>
        <br />
        <label>Signals:&nbsp;
          {['macd_cross', 'bollinger'].map((sig) => (
            <span key={sig} style={{ marginRight: '1rem' }}>
              <input type="checkbox" checked={signals[sig]} onChange={(e) => setSignals({ ...signals, [sig]: e.target.checked })} /> {sig}
            </span>
          ))}
        </label>
        <br />
        <label>Logic:&nbsp;
          <select value={logic} onChange={(e) => setLogic(e.target.value)}>
            <option value="and">AND</option>
            <option value="or">OR</option>
          </select>
        </label>
        <br />
        <button type="submit">Run backtest</button>
      </form>
      {message && <p style={{ color: 'red' }}>{message}</p>}
      {result && (
        <div>
          <h2>Results</h2>
          <p>PNL: {(result.pnl * 100).toFixed(2)}%</p>
          <p>Win rate: {(result.win_rate * 100).toFixed(1)}%</p>
          <p>Max drawdown: {(result.max_drawdown * 100).toFixed(2)}%</p>
          <p>Sharpe ratio: {result.sharpe.toFixed(2)}</p>
          <h3>Trades</h3>
          <ul>
            {result.trades.map((t, i) => (
              <li key={i}>Entry {new Date(t.entry_time).toLocaleDateString()} at {t.entry_price.toFixed(2)}, Exit {new Date(t.exit_time).toLocaleDateString()} at {t.exit_price.toFixed(2)}, PnL {(t.profit_pct * 100).toFixed(2)}%</li>
            ))}
          </ul>
          <h3>Examples</h3>
          {examples.map((ex, i) => (
            <div key={i} style={{ marginBottom: '1rem' }}>
              <p>{ex.timestamp}: signal {ex.signal}, outcome {ex.outcome_pct !== null ? (ex.outcome_pct * 100).toFixed(2) + '%' : 'N/A'}</p>
              <img src={ex.chart_url} alt={`Example ${i}`} style={{ maxWidth: '100%' }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}