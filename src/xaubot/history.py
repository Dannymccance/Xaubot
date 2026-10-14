"""Offline MT5 historical candle snapshot importer, with explicit DST schedule.

Requires a separate, one-shot historical MQL5 FILE_COMMON CSV. It never
changes the 30k-bar live bridge or any other MT5 installation.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import Bar
from .feed_audit import feed_sha256
from .mt5_export import _replace_text_atomic, store_feed
from .wine_bridge import REQUIRED

UTC = timezone.utc
SOURCE = "MQL5 CopyRates(PERIOD_M1, historical chunks, position>=1), FILE_COMMON, Wine"


@dataclass(frozen=True)
class Segment:
    start: datetime  # naive broker server wall-clock boundaries
    end: datetime
    minutes: int

    def contains(self, stamp: datetime) -> bool:
        return self.start <= stamp < self.end


def read_schedule(path: Path) -> tuple[Segment, ...]:
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or not isinstance(raw.get("segments"),list) or not raw["segments"]:
        raise ValueError("Broker time schedule must supply a nonempty segments array")
    items=[]
    for row in raw["segments"]:
        if not isinstance(row,dict):
            raise ValueError("Schedule segment must be a JSON object")
        try:
            start=datetime.fromisoformat(row["from_server"])
            end=datetime.fromisoformat(row["until_server"])
            offset=row["offset_minutes"]
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError("Invalid schedule segment boundaries") from exc
        if (start.tzinfo is not None or end.tzinfo is not None or
                not isinstance(offset,int) or isinstance(offset,bool) or
                not -14*60 <= offset <=14*60 or
                end <= start or start.second or end.second or
                start.microsecond or end.microsecond):
            raise ValueError("Invalid broker-local wall-clock segment or offset")
        items.append(Segment(start,end,offset))
    for a,b in zip(items,items[1:]):
        if a.end!=b.start:
            raise ValueError("Schedule segments must be contiguous and ordered (no overlap/gap)")
    return tuple(items)


def historical_bars(source: Path,symbol: str,segments: tuple[Segment,...],
                    *, now: datetime | None=None) -> list[Bar]:
    """Resolve each broker-local server epoch using operator's explicit intervals."""
    clock=(now or datetime.now(UTC)).astimezone(UTC)
    rows=[]
    with source.open("r",newline="",encoding="utf-8-sig") as handle:
        reader=csv.DictReader(handle)
        if reader.fieldnames!=list(REQUIRED):
            raise ValueError("Historical MQL5 CSV has unexpected column names")
        for line,row in enumerate(reader,2):
            if row["symbol"]!=symbol:
                raise ValueError(f"Historical row {line}: symbol mismatch")
            try:
                server_epoch=int(row["server_epoch"])
                wall=datetime.fromtimestamp(server_epoch,UTC).replace(tzinfo=None)
                matches=[segment for segment in segments if segment.contains(wall)]
                if len(matches)!=1:
                    raise ValueError("No unambiguous broker-offset segment for historical candle")
                offset=matches[0].minutes
                timestamp=datetime.fromtimestamp(server_epoch-offset*60,UTC)
                if timestamp.second or timestamp.microsecond:
                    raise ValueError("Non-minute-aligned converted candle")
                if timestamp+timedelta(minutes=1)>clock+timedelta(seconds=15):
                    raise ValueError("Future or forming candle; verify broker time schedule")
                o,h,l,c=(float(row[col]) for col in ("open","high","low","close"))
                if (not all(math.isfinite(x) and x>0 for x in (o,h,l,c))
                        or h<max(o,l,c) or l>min(o,h,c)):
                    raise ValueError("Invalid OHLC")
                if rows and timestamp<=rows[-1].time:
                    raise ValueError("Duplicate or non-monotonic UTC candle; check DST schedule")
                rows.append(Bar(timestamp,o,h,l,c))
            except (TypeError,KeyError,ValueError,OverflowError,OSError) as exc:
                raise ValueError(f"Historical MQL5 row {line}: {exc}") from exc
    if not rows:
        raise ValueError("No completed historical candles were returned from MT5")
    return rows


def import_archive(source: Path,out: Path,symbol: str,schedule: Path,
                   *,operator_attested: bool=False,
                   now: datetime | None=None) -> dict:
    if (source.resolve()==out.resolve() or schedule.resolve()==out.resolve()
            or out.name=="xauusd_m1.csv"):
        raise ValueError("Historical archive must use a NEW, separate CSV path")
    if out.exists() or out.with_suffix(".manifest.json").exists():
        raise ValueError("Historical output already exists; archive is immutable, choose a new name")
    schedule_segments=read_schedule(schedule)
    sha_raw=feed_sha256(source)
    sha_schedule=feed_sha256(schedule)
    bars=historical_bars(source,symbol,schedule_segments,now=now)
    if feed_sha256(source)!=sha_raw or feed_sha256(schedule)!=sha_schedule:
        raise ValueError("Raw history or offset schedule changed during import")
    status=store_feed(
        out,bars,symbol,now,
        source=SOURCE,broker_utc_offset_minutes=None,
    )
    manifest=out.with_suffix(".manifest.json")
    status.update({
        "history_archive":True,
        "raw_history_sha256":sha_raw,
        "offset_schedule_sha256":sha_schedule,
        "offset_schedule_operator_attested":operator_attested,
        "broker_offset_independently_verified":False,
        "historical_timezone_conversion":"explicit operator-supplied broker wall-clock segments",
        "first_open_utc":bars[0].time.isoformat(),
        "warning":"This is MT5 chart OHLC history, not tick-level Vantage bid/ask. An operator-attested offset is not independently verified.",
    })
    _replace_text_atomic(manifest,json.dumps(status,indent=2)+"\n")
    return status


def main() -> None:
    p=argparse.ArgumentParser(description="Offline read-only historical MT5 XAUUSD -> UTC archive")
    p.add_argument("--raw",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--symbol",default="XAUUSD")
    p.add_argument("--offset-schedule",required=True,type=Path)
    p.add_argument("--operator-attests-offsets",action="store_true")
    args=p.parse_args()
    try:
        result=import_archive(args.raw,args.out,args.symbol,args.offset_schedule,
                              operator_attested=args.operator_attests_offsets)
        print(json.dumps(result,indent=2))
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        p.error(f"Historical archive not imported: {exc}")


if __name__=="__main__":
    main()
