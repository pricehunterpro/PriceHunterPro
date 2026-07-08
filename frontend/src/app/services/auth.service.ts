import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, map, catchError, of } from 'rxjs';

const TOKEN_KEY = 'ph_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http   = inject(HttpClient);
  private router = inject(Router);

  login(username: string, password: string): Observable<boolean> {
    return this.http.post<{ access_token: string }>('/api/v1/auth/admin-login', { username, password }).pipe(
      map(res => {
        localStorage.setItem(TOKEN_KEY, res.access_token);
        return true;
      }),
      catchError(() => of(false)),
    );
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  private _payload(): Record<string, any> | null {
    const token = this.getToken();
    if (!token) return null;
    try {
      return JSON.parse(atob(token.split('.')[1]));
    } catch {
      return null;
    }
  }

  isLoggedIn(): boolean {
    const p = this._payload();
    return !!p && p['exp'] * 1000 > Date.now();
  }

  getRole(): string {
    return this._payload()?.['role'] ?? 'viewer';
  }

  getUsername(): string {
    return this._payload()?.['sub'] ?? '';
  }

  isAdmin(): boolean {
    const role = this.getRole();
    return role === 'admin' || role === 'superadmin';
  }
}
