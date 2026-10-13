// XaubotM1Exporter.mq5
// Read-only XAUUSD M1 data exporter for MetaTrader 5 running in Wine.
// File output only. No CTrade, no OrderSend, no position access, no broker login.
#property copyright "Xaubot research"
#property version   "1.00"
#property strict
#property description "Read-only M1 candle export. No trades. Requires UTC conversion in Python."

input string InpExpectedSymbol = "XAUUSD";
input int    InpHistoryBars = 30000;
input int    InpTimerSeconds = 30;
input string InpOutputName = "xaubot_xauusd_m1_server.csv";

datetime last_published_close = 0;

// Publish only fully closed M1 rates (position 1; position 0 still forms).
bool PublishClosedCandles()
{
   if(_Symbol != InpExpectedSymbol)
   {
      Print("Xaubot: attached to the wrong symbol; refusing export.");
      return false;
   }

   MqlRates bars[];
   ArraySetAsSeries(bars, false);
   ResetLastError();
   int copied = CopyRates(_Symbol, PERIOD_M1, 1, InpHistoryBars, bars);
   if(copied <= 0)
   {
      PrintFormat("Xaubot: M1 history not ready; CopyRates error %d", GetLastError());
      return false;
   }
   datetime newest = bars[copied - 1].time;
   if(newest <= last_published_close)
      return true;
   for(int i = 1; i < copied; i++)
   {
      if(bars[i].time <= bars[i - 1].time)
      {
         Print("Xaubot: unordered M1 history; refusing export.");
         return false;
      }
   }

   string temp = InpOutputName + ".tmp";
   int f = FileOpen(temp, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON,
                    ',', CP_UTF8);
   if(f == INVALID_HANDLE)
   {
      PrintFormat("Xaubot: CSV open failed (%d)", GetLastError());
      return false;
   }
   FileWrite(f, "symbol", "server_epoch", "open", "high", "low", "close");
   for(int i = 0; i < copied; i++)
   {
      FileWrite(f, _Symbol,
                IntegerToString((long)bars[i].time),
                DoubleToString(bars[i].open, _Digits),
                DoubleToString(bars[i].high, _Digits),
                DoubleToString(bars[i].low, _Digits),
                DoubleToString(bars[i].close, _Digits));
   }
   FileFlush(f);
   FileClose(f);

   // Move to the final name only after the complete CSV is closed.
   // Both paths are within MT5's sandboxed common Files directory.
   ResetLastError();
   if(!FileMove(temp, FILE_COMMON, InpOutputName, FILE_COMMON | FILE_REWRITE))
   {
      PrintFormat("Xaubot: CSV publish failed (%d)", GetLastError());
      return false;
   }
   last_published_close = newest;
   PrintFormat("Xaubot: exported %d closed M1 bars for %s, broker time %s; file: %s\\Files\\%s",
               copied, _Symbol, TimeToString(newest, TIME_DATE | TIME_MINUTES),
               TerminalInfoString(TERMINAL_COMMONDATA_PATH), InpOutputName);
   return true;
}

int OnInit()
{
   if(InpExpectedSymbol == "" || _Symbol != InpExpectedSymbol ||
      InpHistoryBars < 100 || InpHistoryBars > 100000 ||
      InpTimerSeconds < 5 || InpTimerSeconds > 3600 ||
      StringFind(InpOutputName, "/") >= 0 ||
      StringFind(InpOutputName, "\\") >= 0 ||
      InpOutputName == "")
   {
      Print("Xaubot: invalid parameters or wrong symbol.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(_Period != PERIOD_M1)
      Print("Xaubot: recommended chart timeframe is M1 (rates are forced to M1).");
   PrintFormat("Xaubot: MARKET DATA ONLY. Common Files path: %s\\Files",
               TerminalInfoString(TERMINAL_COMMONDATA_PATH));
   if(!EventSetTimer(InpTimerSeconds))
      return INIT_FAILED;
   PublishClosedCandles();
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   PublishClosedCandles();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}
