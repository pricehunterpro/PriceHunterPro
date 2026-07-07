import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

export interface TikTokVideo {
  id: string; opportunityId: string;
  titulo: string; store: string; category: string;
  currentPrice: number; originalPrice: number; discountPct: number;
  imageUrl: string; url: string;
  guion: string; hashtags: string[];
  plantilla: string; duracion: number; animacion: string; logoPos: string;
  estado: string; scoreIA: number;
  fechaProgramada: string | null; fechaPublicacion: string | null;
  createdAt: string;
}

interface Kpis {
  pendientes: number; generados: number; programados: number;
  publicados: number; errores: number;
}

const PLANTILLAS = ['Flash Sale','Mega Oferta','Gaming','Tecnología','Hogar','Top Oferta del Día'];
const DURACIONES = [10, 15, 20, 30];
const ANIMACIONES = ['Zoom', 'Slide', 'Fade'];
const LOGO_POS = ['Superior', 'Inferior'];

@Component({
  selector: 'app-tiktok-factory',
  templateUrl: './tiktok-factory.component.html',
  styleUrls: ['./tiktok-factory.component.css'],
  standalone: true,
  imports: [CommonModule, FormsModule],
})
export class TiktokFactoryComponent implements OnInit {
  private http = inject(HttpClient);

  videos: TikTokVideo[] = [];
  kpis: Kpis = { pendientes:0, generados:0, programados:0, publicados:0, errores:0 };
  loading = true;

  selected: TikTokVideo | null = null;

  // Config panel
  plantillas = PLANTILLAS;
  duraciones = DURACIONES;
  animaciones = ANIMACIONES;
  logoPosOpts = LOGO_POS;

  cfgPlantilla = 'Flash Sale';
  cfgDuracion  = 15;
  cfgAnimacion = 'Zoom';
  cfgLogoPos   = 'Superior';

  guionEdit = '';
  regenerating = false;

  scheduleDate = '';
  showScheduler = false;

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.http.get<{ videos: TikTokVideo[]; kpis: Kpis }>('/api/v1/tiktok/videos').subscribe({
      next: r => { this.videos = r.videos; this.kpis = r.kpis; this.loading = false; },
      error: () => { this.loading = false; },
    });
  }

  select(v: TikTokVideo): void {
    this.selected = v;
    this.guionEdit = v.guion;
    this.cfgPlantilla = v.plantilla;
    this.cfgDuracion  = v.duracion;
    this.cfgAnimacion = v.animacion;
    this.cfgLogoPos   = v.logoPos;
    this.showScheduler = false;
  }

  generate(v: TikTokVideo): void {
    v.estado = 'Generando';
    this.http.post<TikTokVideo>('/api/v1/tiktok/generate', {
      opportunityId: v.opportunityId, titulo: v.titulo, store: v.store,
      currentPrice: v.currentPrice, originalPrice: v.originalPrice,
      discountPct: v.discountPct, imageUrl: v.imageUrl, category: v.category,
      plantilla: this.cfgPlantilla, duracion: this.cfgDuracion,
      animacion: this.cfgAnimacion, logoPos: this.cfgLogoPos, scoreIA: v.scoreIA,
    }).subscribe({ next: nv => { this.load(); this.select(nv); }, error: () => { v.estado = 'Error'; } });
  }

  approve(v: TikTokVideo): void {
    this.http.post(`/api/v1/tiktok/approve/${v.id}`, {}).subscribe({ next: () => { v.estado = 'Aprobado'; if (this.selected?.id === v.id) this.selected.estado = 'Aprobado'; } });
  }

  schedule(v: TikTokVideo): void {
    if (!this.scheduleDate) return;
    this.http.post(`/api/v1/tiktok/schedule/${v.id}`, { fecha: this.scheduleDate }).subscribe({
      next: () => { v.estado = 'Programado'; v.fechaProgramada = this.scheduleDate; if (this.selected?.id === v.id) { this.selected.estado = 'Programado'; this.selected.fechaProgramada = this.scheduleDate; } this.showScheduler = false; },
    });
  }

  publish(v: TikTokVideo): void {
    this.http.post(`/api/v1/tiktok/publish/${v.id}`, {}).subscribe({ next: () => { v.estado = 'Publicado'; if (this.selected?.id === v.id) this.selected.estado = 'Publicado'; this.load(); } });
  }

  remove(v: TikTokVideo): void {
    this.http.delete(`/api/v1/tiktok/videos/${v.id}`).subscribe({ next: () => { if (this.selected?.id === v.id) this.selected = null; this.load(); } });
  }

  regenerateGuion(): void {
    if (!this.selected) return;
    this.regenerating = true;
    this.http.post<{ guion: string }>(`/api/v1/tiktok/regenerate-guion/${this.selected.id}`, {}).subscribe({
      next: r => { if (this.selected) { this.selected.guion = r.guion; this.guionEdit = r.guion; } this.regenerating = false; },
      error: () => { this.regenerating = false; },
    });
  }

  statusClass(st: string): string {
    const m: Record<string, string> = {
      'Pendiente':'tt-st-pend', 'Generando':'tt-st-gen', 'Generado':'tt-st-done',
      'Aprobado':'tt-st-apro', 'Programado':'tt-st-sched', 'Publicado':'tt-st-pub', 'Error':'tt-st-err',
    };
    return m[st] ?? 'tt-st-pend';
  }

  storeClass(store: string): string { return `store-${store}`; }

  scoreColor(s: number): string {
    if (s >= 90) return '#ff4d00';
    if (s >= 80) return '#00E58F';
    if (s >= 70) return '#ffd700';
    return '#5a5a6e';
  }
}
