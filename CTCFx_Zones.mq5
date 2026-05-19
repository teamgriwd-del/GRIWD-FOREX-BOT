//+------------------------------------------------------------------+
//|  CTCFx_Zones.mq5                                                 |
//|  Synthetic Trading Bot — Live Zone Indicator                     |
//|  Draws: Buy/Sell Zones, Order Blocks, FVGs, Trend Lines,         |
//|         Swing Highs/Lows, Liquidity Sweeps, Equilibrium          |
//+------------------------------------------------------------------+
#property copyright   "CTCFx Bot"
#property version     "1.10"
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

//── Inputs ───────────────────────────────────────────────────────────
input group "=== DETECTION SETTINGS ==="
input int   InpSwingLB      = 5;     // Swing lookback (bars each side)
input int   InpATRPeriod    = 14;    // ATR period
input int   InpFVGBars      = 150;   // Bars to scan for FVGs
input int   InpOBBars       = 150;   // Bars to scan for Order Blocks
input double InpOBMult      = 2.0;   // OB impulse = X * ATR
input int   InpConsolBars   = 20;    // Consolidation detection bars
input double InpConsolMult  = 0.5;   // Consolidation tight = X * ATR

input group "=== DISPLAY TOGGLES ==="
input bool  ShowBuyZones    = true;
input bool  ShowSellZones   = true;
input bool  ShowOBs         = true;
input bool  ShowFVGs        = true;
input bool  ShowTrendLines  = true;
input bool  ShowSwings      = true;
input bool  ShowSweeps      = true;
input bool  ShowEQ          = true;
input bool  ShowLabels      = true;

input group "=== COLORS ==="
input color ClrBuyZone   = C'0,160,64';     // Buy zone
input color ClrSellZone  = C'200,40,40';    // Sell zone
input color ClrOBBull    = C'30,136,229';   // Bullish order block
input color ClrOBBear    = C'183,28,28';    // Bearish order block
input color ClrFVGBull   = C'0,188,212';    // Bullish FVG
input color ClrFVGBear   = C'255,152,0';    // Bearish FVG
input color ClrSupTL     = C'0,200,83';     // Support trend line
input color ClrResTL     = C'239,83,80';    // Resistance trend line
input color ClrSwingHi   = C'239,83,80';    // Swing high marker
input color ClrSwingLo   = C'38,166,154';   // Swing low marker
input color ClrSweep     = C'255,152,0';    // Sweep marker
input color ClrEQ        = C'150,150,150';  // Equilibrium line

input group "=== STYLE ==="
input int   LabelFontSize = 8;
input int   LineWidth     = 2;
input bool  ZonesInBack   = true;   // Draw zones behind candles

//── Globals ───────────────────────────────────────────────────────────
string PFX = "CTCFx_";
int    atr_handle;
int    prev_bars = 0;

//── Object name helpers ───────────────────────────────────────────────
string OBJ(string tag){ return PFX + tag; }

//+------------------------------------------------------------------+
int OnInit()
{
   atr_handle = iATR(_Symbol, _Period, InpATRPeriod);
   if(atr_handle == INVALID_HANDLE){ Print("ATR init failed"); return INIT_FAILED; }
   IndicatorSetString(INDICATOR_SHORTNAME, "CTCFx Zones");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, PFX);
   ChartRedraw();
}

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double   &open[],
                const double   &high[],
                const double   &low[],
                const double   &close[],
                const long     &tick_volume[],
                const long     &volume[],
                const int      &spread[])
{
   if(rates_total < InpATRPeriod + InpSwingLB * 2 + 5) return 0;

   // Only full redraw on new bar or first run
   bool new_bar = (rates_total != prev_bars);
   if(!new_bar && prev_calculated > 0) return rates_total;
   prev_bars = rates_total;

   // Get ATR buffer
   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(atr_handle, 0, 0, rates_total, atr) <= 0) return 0;

   // Work arrays as series (index 0 = latest bar)
   double H[], L[], O[], C[];
   datetime T[];
   ArraySetAsSeries(H, true); ArraySetAsSeries(L, true);
   ArraySetAsSeries(O, true); ArraySetAsSeries(C, true);
   ArraySetAsSeries(T, true);
   ArrayCopy(H, high); ArrayCopy(L, low);
   ArrayCopy(O, open); ArrayCopy(C, close);
   ArrayCopy(T, time);

   int total = rates_total;

   // Delete old drawings
   ObjectsDeleteAll(0, PFX);

   //── 1. Swing points ─────────────────────────────────────────────
   int max_swing = MathMin(total - InpSwingLB - 1, 300);
   int sh_idx[], sl_idx[];
   double sh_price[], sl_price[];
   int sh_count = 0, sl_count = 0;
   ArrayResize(sh_idx, 50); ArrayResize(sh_price, 50);
   ArrayResize(sl_idx, 50); ArrayResize(sl_price, 50);

   for(int i = InpSwingLB; i < max_swing; i++)
   {
      bool is_sh = true, is_sl = true;
      for(int k = 1; k <= InpSwingLB; k++)
      {
         if(H[i] <= H[i-k] || H[i] <= H[i+k]) is_sh = false;
         if(L[i] >= L[i-k] || L[i] >= L[i+k]) is_sl = false;
      }
      if(is_sh && sh_count < 50){ sh_idx[sh_count] = i; sh_price[sh_count] = H[i]; sh_count++; }
      if(is_sl && sl_count < 50){ sl_idx[sl_count] = i; sl_price[sl_count] = L[i]; sl_count++; }
   }

   // Draw swing markers
   if(ShowSwings)
   {
      for(int i = 0; i < sh_count; i++)
      {
         string nm = OBJ("SH_"+IntegerToString(i));
         if(ObjectCreate(0, nm, OBJ_ARROW, 0, T[sh_idx[i]], H[sh_idx[i]] + atr[sh_idx[i]]*0.3))
         {
            ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, 218);  // down arrow
            ObjectSetInteger(0, nm, OBJPROP_COLOR,     ClrSwingHi);
            ObjectSetInteger(0, nm, OBJPROP_WIDTH,     2);
            ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         }
      }
      for(int i = 0; i < sl_count; i++)
      {
         string nm = OBJ("SL_"+IntegerToString(i));
         if(ObjectCreate(0, nm, OBJ_ARROW, 0, T[sl_idx[i]], L[sl_idx[i]] - atr[sl_idx[i]]*0.3))
         {
            ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, 217);  // up arrow
            ObjectSetInteger(0, nm, OBJPROP_COLOR,     ClrSwingLo);
            ObjectSetInteger(0, nm, OBJPROP_WIDTH,     2);
            ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         }
      }
   }

   //── 2. Market trend via last 2 swings ───────────────────────────
   string trend = "unknown";
   if(sh_count >= 2 && sl_count >= 2)
   {
      bool hh = sh_price[0] > sh_price[1];
      bool hl = sl_price[0] > sl_price[1];
      bool ll = sl_price[0] < sl_price[1];
      bool lh = sh_price[0] < sh_price[1];
      if(hh && hl) trend = "uptrend";
      else if(ll && lh) trend = "downtrend";
      else trend = "consolidation";
   }

   //── 3. FVG detection ─────────────────────────────────────────────
   int fvg_limit = MathMin(total - 2, InpFVGBars);
   if(ShowFVGs)
   {
      int fvg_count = 0;
      for(int i = 1; i < fvg_limit && fvg_count < 20; i++)
      {
         // Bullish FVG: candle[i+1].high < candle[i-1].low  (gap up)
         // In series order: H[i+1] < L[i-1]
         if(H[i+1] < L[i-1])
         {
            double ftop = L[i-1];
            double fbot = H[i+1];
            if(ftop > fbot)
            {
               // Check if filled (any subsequent close below fbot)
               bool filled = false;
               for(int j = 0; j < i-1; j++) if(C[j] < fbot){ filled = true; break; }
               if(!filled)
               {
                  string nm = OBJ("FVGB_"+IntegerToString(fvg_count));
                  DrawZoneRect(nm, T[i], T[0], ftop, fbot,
                               ClrFVGBull, STYLE_DASH, 1, ZonesInBack);
                  if(ShowLabels)
                  {
                     string lnm = OBJ("FVGB_L"+IntegerToString(fvg_count));
                     DrawLabel(lnm, T[i], ftop, "FVG+", ClrFVGBull);
                  }
                  fvg_count++;
               }
            }
         }
         // Bearish FVG: candle[i+1].low > candle[i-1].high (gap down)
         if(L[i+1] > H[i-1])
         {
            double ftop = L[i+1];
            double fbot = H[i-1];
            if(ftop > fbot)
            {
               bool filled = false;
               for(int j = 0; j < i-1; j++) if(C[j] > ftop){ filled = true; break; }
               if(!filled)
               {
                  string nm = OBJ("FVGR_"+IntegerToString(fvg_count));
                  DrawZoneRect(nm, T[i], T[0], ftop, fbot,
                               ClrFVGBear, STYLE_DASH, 1, ZonesInBack);
                  if(ShowLabels)
                  {
                     string lnm = OBJ("FVGR_L"+IntegerToString(fvg_count));
                     DrawLabel(lnm, T[i], ftop, "FVG-", ClrFVGBear);
                  }
                  fvg_count++;
               }
            }
         }
      }
   }

   //── 4. Order Blocks ──────────────────────────────────────────────
   int ob_limit = MathMin(total - InpSwingLB - 1, InpOBBars);
   if(ShowOBs)
   {
      int ob_count = 0;
      for(int i = InpSwingLB; i < ob_limit && ob_count < 20; i++)
      {
         if(atr[i] <= 0) continue;
         double future_hi = 0, future_lo = 9e10;
         for(int k = 1; k <= InpSwingLB && (i-k) >= 0; k++)
         {
            future_hi = MathMax(future_hi, H[i-k]);
            future_lo = MathMin(future_lo, L[i-k]);
         }
         double imp_up   = future_hi - C[i];
         double imp_down = C[i] - future_lo;

         // Bullish OB: bearish candle + big move up
         if(C[i] < O[i] && imp_up > atr[i] * InpOBMult)
         {
            double ob_top = O[i], ob_bot = C[i];
            bool broken = false;
            for(int k = 1; k < i && k < 30; k++) if(C[k] < ob_bot){ broken = true; break; }
            if(!broken)
            {
               string nm = OBJ("OBB_"+IntegerToString(ob_count));
               DrawZoneRect(nm, T[i], T[0], ob_top, ob_bot,
                            ClrOBBull, STYLE_SOLID, LineWidth, false);
               if(ShowLabels)
               {
                  string lnm = OBJ("OBB_L"+IntegerToString(ob_count));
                  DrawLabel(lnm, T[i], ob_top, "OB+", ClrOBBull);
               }
               ob_count++;
            }
         }
         // Bearish OB: bullish candle + big move down
         else if(C[i] > O[i] && imp_down > atr[i] * InpOBMult)
         {
            double ob_top = C[i], ob_bot = O[i];
            bool broken = false;
            for(int k = 1; k < i && k < 30; k++) if(C[k] > ob_top){ broken = true; break; }
            if(!broken)
            {
               string nm = OBJ("OBR_"+IntegerToString(ob_count));
               DrawZoneRect(nm, T[i], T[0], ob_top, ob_bot,
                            ClrOBBear, STYLE_SOLID, LineWidth, false);
               if(ShowLabels)
               {
                  string lnm = OBJ("OBR_L"+IntegerToString(ob_count));
                  DrawLabel(lnm, T[i], ob_top, "OB-", ClrOBBear);
               }
               ob_count++;
            }
         }
      }
   }

   //── 5. Support / Resistance from swing clusters ──────────────────
   double atr0 = atr[0];
   if(ShowBuyZones && sl_count >= 1)
   {
      for(int i = 0; i < MathMin(sl_count, 8); i++)
      {
         double bot = sl_price[i] - atr0 * 0.5;
         double top = sl_price[i] + atr0 * 0.5;
         string nm = OBJ("BZ_"+IntegerToString(i));
         DrawZoneRect(nm,
                      T[MathMin(sl_idx[i]+20, total-1)], T[0],
                      top, bot,
                      ClrBuyZone, STYLE_DOT, 1, true);
         if(ShowLabels && i == 0)
         {
            string lnm = OBJ("BZ_L"+IntegerToString(i));
            DrawLabel(lnm, T[sl_idx[i]], top, "Buy Zone", ClrBuyZone);
         }
      }
   }
   if(ShowSellZones && sh_count >= 1)
   {
      for(int i = 0; i < MathMin(sh_count, 8); i++)
      {
         double bot = sh_price[i] - atr0 * 0.5;
         double top = sh_price[i] + atr0 * 0.5;
         string nm = OBJ("SZ_"+IntegerToString(i));
         DrawZoneRect(nm,
                      T[MathMin(sh_idx[i]+20, total-1)], T[0],
                      top, bot,
                      ClrSellZone, STYLE_DOT, 1, true);
         if(ShowLabels && i == 0)
         {
            string lnm = OBJ("SZ_L"+IntegerToString(i));
            DrawLabel(lnm, T[sh_idx[i]], top, "Sell Zone", ClrSellZone);
         }
      }
   }

   //── 6. Trend Lines ───────────────────────────────────────────────
   if(ShowTrendLines)
   {
      // Support TL: connect last 2 swing lows
      if(sl_count >= 2)
      {
         string nm = OBJ("TL_SUP");
         if(ObjectCreate(0, nm, OBJ_TREND, 0,
                         T[sl_idx[1]], sl_price[1],
                         T[sl_idx[0]], sl_price[0]))
         {
            ObjectSetInteger(0, nm, OBJPROP_COLOR,     ClrSupTL);
            ObjectSetInteger(0, nm, OBJPROP_STYLE,     STYLE_DASH);
            ObjectSetInteger(0, nm, OBJPROP_WIDTH,     LineWidth);
            ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, true);
            ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         }
         if(ShowLabels) DrawLabel(OBJ("TL_SUP_L"), T[sl_idx[0]], sl_price[0]-atr0*0.5,
                                  "Support TL", ClrSupTL);
      }
      // Resistance TL: connect last 2 swing highs
      if(sh_count >= 2)
      {
         string nm = OBJ("TL_RES");
         if(ObjectCreate(0, nm, OBJ_TREND, 0,
                         T[sh_idx[1]], sh_price[1],
                         T[sh_idx[0]], sh_price[0]))
         {
            ObjectSetInteger(0, nm, OBJPROP_COLOR,     ClrResTL);
            ObjectSetInteger(0, nm, OBJPROP_STYLE,     STYLE_DASH);
            ObjectSetInteger(0, nm, OBJPROP_WIDTH,     LineWidth);
            ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, true);
            ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         }
         if(ShowLabels) DrawLabel(OBJ("TL_RES_L"), T[sh_idx[0]], sh_price[0]+atr0*0.3,
                                  "Resistance TL", ClrResTL);
      }
   }

   //── 7. Liquidity Sweeps ──────────────────────────────────────────
   if(ShowSweeps && atr0 > 0)
   {
      int sw_count = 0;
      for(int i = 1; i < MathMin(total-1, 200) && sw_count < 15; i++)
      {
         double tol = atr[i] * 0.1;
         for(int s = 0; s < sh_count; s++)
         {
            if(sh_idx[s] <= i) continue;
            if(H[i] > sh_price[s] + tol && C[i] < sh_price[s])
            {
               string nm = OBJ("SWH_"+IntegerToString(sw_count));
               if(ObjectCreate(0, nm, OBJ_ARROW, 0, T[i], H[i]+atr[i]*0.3))
               {
                  ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, 251);
                  ObjectSetInteger(0, nm, OBJPROP_COLOR,     ClrSweep);
                  ObjectSetInteger(0, nm, OBJPROP_WIDTH,     3);
                  ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
               }
               if(ShowLabels) DrawLabel(OBJ("SWH_L"+IntegerToString(sw_count)),
                                        T[i], H[i]+atr[i]*0.6, "SWEEP", ClrSweep);
               sw_count++; break;
            }
         }
         for(int s = 0; s < sl_count; s++)
         {
            if(sl_idx[s] <= i) continue;
            if(L[i] < sl_price[s] - tol && C[i] > sl_price[s])
            {
               string nm = OBJ("SWL_"+IntegerToString(sw_count));
               if(ObjectCreate(0, nm, OBJ_ARROW, 0, T[i], L[i]-atr[i]*0.3))
               {
                  ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, 251);
                  ObjectSetInteger(0, nm, OBJPROP_COLOR,     C'171,71,188');
                  ObjectSetInteger(0, nm, OBJPROP_WIDTH,     3);
                  ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
               }
               if(ShowLabels) DrawLabel(OBJ("SWL_L"+IntegerToString(sw_count)),
                                        T[i], L[i]-atr[i]*0.7, "SWEEP", C'171,71,188');
               sw_count++; break;
            }
         }
      }
   }

   //── 8. Equilibrium line ──────────────────────────────────────────
   if(ShowEQ)
   {
      int eq_bars = MathMin(total, InpConsolBars);
      double eq_high = 0, eq_low = 9e10;
      for(int i = 0; i < eq_bars; i++){ eq_high = MathMax(eq_high,H[i]); eq_low = MathMin(eq_low,L[i]); }
      double eq = (eq_high + eq_low) / 2.0;
      string nm = OBJ("EQ");
      if(ObjectCreate(0, nm, OBJ_HLINE, 0, 0, eq))
      {
         ObjectSetInteger(0, nm, OBJPROP_COLOR,     ClrEQ);
         ObjectSetInteger(0, nm, OBJPROP_STYLE,     STYLE_DOT);
         ObjectSetInteger(0, nm, OBJPROP_WIDTH,     1);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      }
      if(ShowLabels) DrawLabel(OBJ("EQ_L"), T[3], eq + atr0*0.1,
                               "EQ  "+DoubleToString(eq,_Digits), ClrEQ);
   }

   //── 9. Trend label ───────────────────────────────────────────────
   if(ShowLabels)
   {
      color tc = trend=="uptrend" ? ClrSupTL : (trend=="downtrend" ? ClrResTL : ClrEQ);
      DrawLabel(OBJ("TREND_LBL"), T[1], H[0]+atr0,
                "Trend: "+trend, tc, 10);
   }

   ChartRedraw();
   return rates_total;
}

//── Helper: Draw filled zone rectangle ───────────────────────────────
void DrawZoneRect(string name,
                  datetime t1, datetime t2,
                  double price_top, double price_bot,
                  color clr, ENUM_LINE_STYLE style,
                  int width, bool in_back)
{
   if(ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, price_top, t2, price_bot))
   {
      ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
      ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
      ObjectSetInteger(0, name, OBJPROP_FILL,       true);
      ObjectSetInteger(0, name, OBJPROP_BACK,       in_back);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
   }
}

//── Helper: Draw text label ─────────────────────────────────────────
void DrawLabel(string name, datetime t, double price,
               string text, color clr, int fontsize = 0)
{
   if(fontsize == 0) fontsize = LabelFontSize;
   if(ObjectCreate(0, name, OBJ_TEXT, 0, t, price))
   {
      ObjectSetString (0, name, OBJPROP_TEXT,      text);
      ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  fontsize);
      ObjectSetString (0, name, OBJPROP_FONT,      "Consolas");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN,    true);
   }
}
//+------------------------------------------------------------------+
