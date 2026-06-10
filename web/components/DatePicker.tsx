"use client";

import { useId } from "react";
import { formatDisplayDate, localTodayIso } from "@/lib/format";
import styles from "./DatePicker.module.css";

interface DatePickerProps {
  value: string;
  onChange: (date: string) => void;
  disabled?: boolean;
}

export function DatePicker({ value, onChange, disabled }: DatePickerProps) {
  const inputId = useId();
  const isToday = value === localTodayIso();

  function shiftDays(delta: number) {
    const [y, m, d] = value.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    date.setDate(date.getDate() + delta);
    const ny = date.getFullYear();
    const nm = String(date.getMonth() + 1).padStart(2, "0");
    const nd = String(date.getDate()).padStart(2, "0");
    onChange(`${ny}-${nm}-${nd}`);
  }

  return (
    <div className={styles.picker}>
      <button
        type="button"
        className={styles.navButton}
        aria-label="Previous day"
        onClick={() => shiftDays(-1)}
        disabled={disabled}
      >
        ◀
      </button>

      <label htmlFor={inputId} className={styles.dateLabel}>
        <span className={styles.dateDisplay}>{formatDisplayDate(value)}</span>
        <input
          id={inputId}
          type="date"
          className={styles.dateInput}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          aria-label="Select date"
        />
      </label>

      <button
        type="button"
        className={styles.navButton}
        aria-label="Next day"
        onClick={() => shiftDays(1)}
        disabled={disabled}
      >
        ▶
      </button>

      {!isToday && (
        <button
          type="button"
          className={styles.todayButton}
          onClick={() => onChange(localTodayIso())}
          disabled={disabled}
        >
          Today
        </button>
      )}
    </div>
  );
}
