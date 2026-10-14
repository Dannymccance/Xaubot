// XaubotHistorySnapshot.mq5 - one-shot, READ ONLY MT5 XAUUSD history archive.
// Place in the dedicated xaumt5 terminal's MQL5/Scripts; run manually.
// Does NOT alter XaubotM1Exporter or any DKcapital terminal or account.
// Writes server-local times to a SEPARATE FILE_COMMON file. No orders, login or stops.
#property copyright "Xaubot research"
#property version   "1.00"
#property strict
#property script_show_inputs

input string InpExpectedSymbol="XAUUSD";
input int InpRequestedBars=500000;  // historical completed M1 bars requested
input int InpChunkBars=10000;      // older -> newer; latest forming bar excluded
input string InpOutputName="xaubot_history_xauusd_m1_server.csv";

void OnStart()
{
   if(_Symbol!=InpExpectedSymbol ||
      InpRequestedBars<1000 || InpRequestedBars>750000 ||
      InpChunkBars<100 || InpChunkBars>20000 ||
      StringFind(InpOutputName,"xaubot_history_")!=0 ||
      StringFind(InpOutputName,"/")>=0 ||
      StringFind(InpOutputName,"\\")>=0 ||
      StringFind(InpOutputName,"..")>=0 ||
      StringFind(InpOutputName,".csv")<0 ||
      InpOutputName=="xaubot_xauusd_m1_server.csv")
   {
      Print("Xaubot history: invalid settings; run only on the Xaubot XAUUSD chart.");
      return;
   }

   // Bars() is bounded by locally available MT5 history and chart limits.
   // Older server candles are NOT guaranteed to be downloaded.
   int available=Bars(_Symbol,PERIOD_M1);
   int closed=available-1;
   if(closed<1000)
   {
      PrintFormat("Xaubot history: MT5 only has %d available completed M1 bars. Load more history first.",closed);
      return;
   }
   int desired=MathMin(closed,InpRequestedBars);
   if(desired<InpRequestedBars)
      PrintFormat("Xaubot history: only %d/%d requested closed M1 bars locally available. Partial snapshot is labelled.",
                  desired,InpRequestedBars);

   string tmp=InpOutputName+".tmp";
   int handle=FileOpen(tmp,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',',CP_UTF8);
   if(handle==INVALID_HANDLE)
   {
      PrintFormat("Xaubot history: cannot write separate CSV, error %d",GetLastError());
      return;
   }
   FileWrite(handle,"symbol","server_epoch","open","high","low","close");
   int written=0;
   datetime last=0;
   bool failed=false;
   // CopyRates(start_pos=1) omits unfinished candle 0. Iterate backward
   // through requested positions, then write each batch oldest-to-newest.
   for(int remaining=desired;remaining>0;)
   {
      int count=MathMin(InpChunkBars,remaining);
      int start_pos=remaining-count+1;
      MqlRates batch[];
      ArraySetAsSeries(batch,false);
      ResetLastError();
      int got=CopyRates(_Symbol,PERIOD_M1,start_pos,count,batch);
      if(got!=count)
      {
         PrintFormat("Xaubot history: requested %d at position %d, received %d, error %d; snapshot not published.",
                     count,start_pos,got,GetLastError());
         failed=true;
         break;
      }
      for(int i=0;i<got;i++)
      {
         if(last>0 && batch[i].time<=last)
         {
            Print("Xaubot history: overlapping/unsorted closed M1 candles; refusing snapshot.");
            failed=true;
            break;
         }
         last=batch[i].time;
         FileWrite(handle,_Symbol,IntegerToString((long)batch[i].time),
                   DoubleToString(batch[i].open,_Digits),
                   DoubleToString(batch[i].high,_Digits),
                   DoubleToString(batch[i].low,_Digits),
                   DoubleToString(batch[i].close,_Digits));
         written++;
      }
      if(failed)
         break;
      remaining=start_pos-1;
   }
   FileFlush(handle);
   FileClose(handle);
   if(failed || written!=desired)
   {
      FileDelete(tmp,FILE_COMMON);
      Print("Xaubot history: failed; existing archive and live feed unchanged.");
      return;
   }
   ResetLastError();
   if(!FileMove(tmp,FILE_COMMON,InpOutputName,FILE_COMMON|FILE_REWRITE))
   {
      PrintFormat("Xaubot history: publication failed, error %d",GetLastError());
      FileDelete(tmp,FILE_COMMON);
      return;
   }
   PrintFormat("Xaubot history: finished %d of %d requested completed M1 bars (MT5 locally available=%d). Last broker open %s. Separate file %s\\Files\\%s",
               written,InpRequestedBars,closed,TimeToString(last,TIME_DATE|TIME_MINUTES),
               TerminalInfoString(TERMINAL_COMMONDATA_PATH),InpOutputName);
   Print("Xaubot history: broker-local timestamps; verify server-to-UTC offset AND historic DST before conversion.");
}
