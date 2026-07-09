import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface Channel {
  id: string; nombre: string; api: string; color: string; estado: string;
  cuenta_conectada: string; token_masked: string; tiene_token: boolean;
  expiracion: string | null; ultima_publicacion: string | null; created_at: string; updated_at: string;
}
interface Kpis { total: number; conectados: number; desconectados: number; conError: number; }

@Component({
  selector: 'app-canales',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './canales.component.html',
  styleUrls: ['./canales.component.css'],
})
export class CanalesComponent implements OnInit {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/channels';

  loading = false;
  items: Channel[] = [];
  kpis: Kpis | null = null;

  // Modal conectar / actualizar token
  showConnect = false;
  connectMode: 'connect' | 'update' = 'connect';
  target: Channel | null = null;
  tokenInput = ''; cuentaInput = ''; expInput = '';
  saving = false;

  toast = '';
  private toastTimer: any = null;

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading = true;
    this.http.get<any>(this.base).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; },
      error: () => { this.items = []; },
    });
    this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} });
  }

  openConnect(c: Channel, mode: 'connect' | 'update' = 'connect'): void {
    this.target = c; this.connectMode = mode;
    this.tokenInput = ''; this.cuentaInput = c.cuenta_conectada || ''; this.expInput = '';
    this.showConnect = true;
  }
  closeConnect(): void { this.showConnect = false; }

  saveConnect(): void {
    if (!this.target) return;
    if (!this.tokenInput.trim()) { this.showToast('Ingresa el token'); return; }
    this.saving = true;
    const path = this.connectMode === 'update' ? 'update-token' : 'connect';
    const body: any = { token: this.tokenInput };
    if (this.connectMode === 'connect') { body.cuenta = this.cuentaInput; if (this.expInput) body.expiracion = this.expInput; }
    this.http.post<any>(`${this.base}/${this.target.id}/${path}`, body).pipe(finalize(() => this.saving = false)).subscribe({
      next: () => { this.showConnect = false; this.showToast(this.connectMode === 'update' ? 'Token actualizado' : 'Canal conectado'); this.load(); },
      error: e => this.showToast(e?.error?.detail || 'Error'),
    });
  }
  disconnect(c: Channel): void {
    if (!confirm(`¿Desconectar ${c.nombre}?`)) return;
    this.http.post<any>(`${this.base}/${c.id}/disconnect`, {}).subscribe({
      next: () => { this.showToast(`${c.nombre} desconectado`); this.load(); },
      error: () => this.showToast('Error'),
    });
  }
  test(c: Channel): void {
    this.showToast(`Probando ${c.nombre}…`);
    this.http.post<any>(`${this.base}/${c.id}/test`, {}).subscribe({
      next: r => {
        if (r.real) this.showToast(`✔ ${c.nombre} conectado: ${r.detail.bot ? '@' + r.detail.bot : 'OK'}`);
        else this.showToast(`✔ ${r.detail.mensaje}`);
        this.load();
      },
      error: e => this.showToast(e?.error?.detail || 'Falló la prueba'),
    });
  }

  private showToast(msg: string): void { this.toast = msg; clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => this.toast = '', 3200); }

  icon(id: string): string {
    const m: Record<string, string> = { telegram: '✈️', facebook: 'f', instagram: '📷', tiktok: '🎵', whatsapp: '💬', youtube: '▶' };
    return m[id] ?? '📡';
  }
  estadoClass(e: string): string {
    const m: Record<string, string> = { Conectado: 'e-ok', Desconectado: 'e-off', Error: 'e-err', Expirado: 'e-exp' };
    return m[e] ?? 'e-off';
  }
}
