import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

interface CalEvent {
  id: string;
  titulo: string;
  store: string;
  category: string;
  discountPct: number;
  currentPrice: number;
  imageUrl: string;
  canales: string[];
  estado: string;      // uno de los 4: Publicado | Programado | Pendiente | Error
  estadoReal: string;  // estado interno del Publicador
  fecha: string | null;
}
interface DayCell { date: Date; inMonth: boolean; isToday: boolean; events: CalEvent[]; }
type Mode = 'mes' | 'semana' | 'agenda';

@Component({
  selector: 'app-calendario',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './calendario.component.html',
  styleUrls: ['./calendario.component.css'],
})
export class CalendarioComponent implements OnInit {
  private http = inject(HttpClient);

  mode: Mode = 'mes';
  anchor = new Date();
  events: CalEvent[] = [];
  kpis: Record<string, number> = {};
  estados: string[] = ['Publicado', 'Programado', 'Pendiente', 'Error'];
  loading = false;
  filterEstado = '';
  selected: CalEvent | null = null;

  readonly weekdayLabels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
  readonly monthNames = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.http.get<{ eventos: CalEvent[]; kpis: Record<string, number>; estados: string[] }>(
      '/api/v1/publicador/calendario',
    ).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => {
        this.events = r.eventos ?? [];
        this.kpis = r.kpis ?? {};
        if (r.estados?.length) this.estados = r.estados;
      },
      error: () => { this.events = []; },
    });
  }

  // ── Filtro ──
  get filteredEvents(): CalEvent[] {
    return this.filterEstado ? this.events.filter(e => e.estado === this.filterEstado) : this.events;
  }
  toggleFilter(estado: string): void {
    this.filterEstado = this.filterEstado === estado ? '' : estado;
  }

  setMode(m: Mode): void { this.mode = m; }

  // ── Navegación ──
  prev(): void { this.shift(-1); }
  next(): void { this.shift(1); }
  today(): void { this.anchor = new Date(); }
  private shift(dir: number): void {
    const d = new Date(this.anchor);
    if (this.mode === 'semana') d.setDate(d.getDate() + dir * 7);
    else d.setMonth(d.getMonth() + dir);
    this.anchor = d;
  }

  // ── Helpers de fecha ──
  private ymd(d: Date): string { return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; }
  private sameDay(a: Date, b: Date): boolean { return this.ymd(a) === this.ymd(b); }
  private startOfWeek(d: Date): Date {
    const x = new Date(d);
    const day = (x.getDay() + 6) % 7; // lunes = 0
    x.setDate(x.getDate() - day);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  eventsForDay(date: Date): CalEvent[] {
    return this.filteredEvents
      .filter(e => e.fecha && this.sameDay(new Date(e.fecha), date))
      .sort((a, b) => (a.fecha! < b.fecha! ? -1 : 1));
  }

  // ── MES: 6 semanas (42 celdas) ──
  get monthCells(): DayCell[] {
    const y = this.anchor.getFullYear(), m = this.anchor.getMonth();
    const start = this.startOfWeek(new Date(y, m, 1));
    const today = new Date();
    const cells: DayCell[] = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      cells.push({ date: d, inMonth: d.getMonth() === m, isToday: this.sameDay(d, today), events: this.eventsForDay(d) });
    }
    return cells;
  }

  // ── SEMANA: 7 días ──
  get weekCells(): DayCell[] {
    const start = this.startOfWeek(this.anchor);
    const today = new Date();
    const cells: DayCell[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      cells.push({ date: d, inMonth: true, isToday: this.sameDay(d, today), events: this.eventsForDay(d) });
    }
    return cells;
  }

  // ── AGENDA: grupos por día ordenados ──
  get agendaGroups(): { date: Date; events: CalEvent[] }[] {
    const map = new Map<string, { date: Date; events: CalEvent[] }>();
    for (const e of this.filteredEvents) {
      if (!e.fecha) continue;
      const d = new Date(e.fecha);
      const key = this.ymd(d);
      if (!map.has(key)) map.set(key, { date: new Date(d.getFullYear(), d.getMonth(), d.getDate()), events: [] });
      map.get(key)!.events.push(e);
    }
    const groups = Array.from(map.values()).sort((a, b) => a.date.getTime() - b.date.getTime());
    for (const g of groups) g.events.sort((a, b) => (a.fecha! < b.fecha! ? -1 : 1));
    return groups;
  }

  // ── Etiquetas ──
  get periodLabel(): string {
    if (this.mode === 'semana') {
      const s = this.startOfWeek(this.anchor);
      const e = new Date(s); e.setDate(s.getDate() + 6);
      const ms = this.monthNames[s.getMonth()].slice(0, 3);
      const me = this.monthNames[e.getMonth()].slice(0, 3);
      return `${s.getDate()} ${ms} – ${e.getDate()} ${me} ${e.getFullYear()}`;
    }
    return `${this.monthNames[this.anchor.getMonth()]} ${this.anchor.getFullYear()}`;
  }

  estadoClass(estado: string): string { return 'st-' + estado.toLowerCase(); }
  weekdayLabel(d: Date): string { return this.weekdayLabels[(d.getDay() + 6) % 7]; }
  agendaDayLabel(d: Date): string {
    const today = new Date();
    if (this.sameDay(d, today)) return 'Hoy';
    const tm = new Date(today); tm.setDate(today.getDate() + 1);
    if (this.sameDay(d, tm)) return 'Mañana';
    return `${this.weekdayLabel(d)} ${d.getDate()} ${this.monthNames[d.getMonth()].slice(0, 3)}`;
  }
  timeLabel(fecha: string | null): string {
    if (!fecha) return '';
    return new Date(fecha).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' });
  }

  select(e: CalEvent): void { this.selected = e; }
  closeDetail(): void { this.selected = null; }
}
