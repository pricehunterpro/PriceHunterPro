import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';

interface User {
  id: string; nombre: string; email: string; role: string; status: string;
  tenant_id: string; permisos: string[]; last_access: string | null; created_at: string; updated_at: string;
}
interface Kpis { activos: number; inactivos: number; administradores: number; ultimosIngresos: number; total: number; }

@Component({
  selector: 'app-usuarios',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './usuarios.component.html',
  styleUrls: ['./usuarios.component.css'],
})
export class UsuariosComponent implements OnInit {
  private http = inject(HttpClient);
  private readonly base = '/api/v1/users';

  loading = false;
  items: User[] = [];
  kpis: Kpis | null = null;
  roles: string[] = [];
  tenants: string[] = [];
  permisosMatrix: Record<string, string[]> = {};
  modulos: string[] = [];

  fRole = ''; fStatus = ''; q = '';

  showForm = false;
  editing: string | null = null;
  form: Partial<User & { password: string }> = {};
  saving = false;

  tempPassword = '';
  toast = '';
  private toastTimer: any = null;

  ngOnInit(): void { this.loadRoles(); this.load(); }

  loadRoles(): void {
    this.http.get<any>(`${this.base}/roles`).subscribe({
      next: r => { this.roles = r.roles ?? []; this.permisosMatrix = r.permisos ?? {}; this.modulos = r.modulos ?? []; this.tenants = r.tenants ?? []; },
      error: () => {},
    });
  }
  load(): void {
    this.loading = true;
    const params: Record<string, string> = {};
    if (this.fRole) params['role'] = this.fRole;
    if (this.fStatus) params['status'] = this.fStatus;
    if (this.q) params['q'] = this.q;
    this.http.get<any>(this.base, { params }).pipe(finalize(() => this.loading = false)).subscribe({
      next: r => { this.items = r.items ?? []; if (r.roles) this.roles = r.roles; if (r.tenants) this.tenants = r.tenants; },
      error: () => { this.items = []; },
    });
    this.http.get<any>(`${this.base}/stats`).subscribe({ next: r => this.kpis = r.kpis ?? null, error: () => {} });
  }
  clearFilters(): void { this.fRole = this.fStatus = this.q = ''; this.load(); }

  // ── Form ──
  openNew(): void { this.editing = null; this.form = { nombre: '', email: '', role: 'Invitado', status: 'Activo', tenant_id: this.tenants[0] || 'PriceHunter Pro', password: '' }; this.showForm = true; }
  openEdit(u: User): void { this.editing = u.id; this.form = { ...u }; this.showForm = true; }
  closeForm(): void { this.showForm = false; }
  get formPermisos(): string[] { return this.permisosMatrix[this.form.role || ''] || []; }

  save(): void {
    if (!(this.form.nombre || '').trim() || !(this.form.email || '').trim()) { this.showToast('Nombre y correo obligatorios'); return; }
    this.saving = true;
    const req = this.editing
      ? this.http.put<any>(`${this.base}/${this.editing}`, this.form)
      : this.http.post<any>(this.base, this.form);
    req.pipe(finalize(() => this.saving = false)).subscribe({
      next: r => {
        this.showForm = false;
        if (r.password_temporal) { this.tempPassword = r.password_temporal; }
        this.showToast(this.editing ? 'Usuario actualizado' : 'Usuario creado');
        this.load();
      },
      error: e => this.showToast(e?.error?.detail || 'Error al guardar'),
    });
  }
  toggleStatus(u: User): void {
    this.http.post<any>(`${this.base}/${u.id}/toggle-status`, {}).subscribe({
      next: r => { this.showToast(`Usuario ${r.item.status === 'Activo' ? 'activado' : 'desactivado'}`); this.load(); },
      error: () => this.showToast('Error'),
    });
  }
  resetPassword(u: User): void {
    if (!confirm(`¿Restablecer la contraseña de ${u.nombre}?`)) return;
    this.http.post<any>(`${this.base}/${u.id}/reset-password`, {}).subscribe({
      next: r => { this.tempPassword = r.password_temporal; this.showToast('Contraseña restablecida'); },
      error: () => this.showToast('Error'),
    });
  }
  remove(u: User): void {
    if (!confirm(`¿Eliminar al usuario ${u.nombre}?`)) return;
    this.http.delete(`${this.base}/${u.id}`).subscribe({
      next: () => { this.showToast('Usuario eliminado'); this.load(); },
      error: () => this.showToast('Error'),
    });
  }
  copyTemp(): void { navigator.clipboard?.writeText(this.tempPassword).then(() => this.showToast('Contraseña copiada')); }

  private showToast(msg: string): void { this.toast = msg; clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => this.toast = '', 2600); }

  roleClass(r: string): string {
    const m: Record<string, string> = { Administrador: 'r-admin', Supervisor: 'r-super', Editor: 'r-editor', Analista: 'r-analista', Invitado: 'r-invitado' };
    return m[r] ?? 'r-invitado';
  }
  initials(n: string): string { return (n || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase(); }
}
