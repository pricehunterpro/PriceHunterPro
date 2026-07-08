import { Component, HostListener, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { DealsStateService } from '../services/deals-state.service';
import { AuthService } from '../services/auth.service';

@Component({
  selector: 'app-layout',
  templateUrl: './app-layout.component.html',
  styleUrls: ['./app-layout.component.css'],
  standalone: true,
  imports: [CommonModule, FormsModule, RouterOutlet, RouterLink, RouterLinkActive],
})
export class AppLayoutComponent implements OnInit {
  protected s    = inject(DealsStateService);
  protected auth = inject(AuthService);
  private router = inject(Router);
  private route  = inject(ActivatedRoute);

  collapsed      = false;
  mobileMenuOpen = false;
  openGroups     = new Set<string>(['oportunidades']);
  headerSearch   = '';

  profileOpen  = false;
  adminKeyInput = '';
  adminKeyError = '';

  ngOnInit(): void {
    const key = this.route.snapshot.queryParamMap.get('key') ?? '';
    if (key === 'ph2026') sessionStorage.setItem('ph_admin', '1');
    this.s.init();
    if (this.auth.isAdmin()) this.s.isAdmin = true;
    // Cierra el menú móvil al navegar a otra ruta
    this.router.events.subscribe(ev => {
      if (ev instanceof NavigationEnd) this.mobileMenuOpen = false;
    });
  }

  toggleMobileMenu(): void { this.mobileMenuOpen = !this.mobileMenuOpen; }
  closeMobileMenu(): void { this.mobileMenuOpen = false; }

  toggle(group: string): void {
    this.openGroups.has(group) ? this.openGroups.delete(group) : this.openGroups.add(group);
  }

  isOpen(g: string): boolean { return !this.collapsed && this.openGroups.has(g); }

  onSearch(): void {
    if (!this.headerSearch.trim()) return;
    this.s.searchQuery = this.headerSearch.trim();
    this.router.navigate(['/oportunidades']);
    this.s.loadDeals();
  }

  clearHeaderSearch(): void {
    this.headerSearch = '';
    this.s.searchQuery = '';
    this.s.loadDeals();
  }

  toggleProfile(): void {
    this.profileOpen  = !this.profileOpen;
    this.adminKeyInput = '';
    this.adminKeyError = '';
  }

  activateAdmin(): void {
    if (this.adminKeyInput === 'ph2026') {
      sessionStorage.setItem('ph_admin', '1');
      this.s.isAdmin   = true;
      this.adminKeyError = '';
      this.profileOpen  = false;
    } else {
      this.adminKeyError = 'Clave incorrecta';
    }
  }

  deactivateAdmin(): void {
    sessionStorage.removeItem('ph_admin');
    this.s.isAdmin  = false;
    this.profileOpen = false;
  }

  logout(): void {
    this.auth.logout();
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(e: MouseEvent): void {
    const target = e.target as HTMLElement;
    if (!target.closest('.h-user-wrap')) this.profileOpen = false;
  }
}
