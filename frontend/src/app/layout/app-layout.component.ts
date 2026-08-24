import { Component, HostListener, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
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

  collapsed      = false;
  mobileMenuOpen = false;
  openGroups     = new Set<string>(['oportunidades']);
  headerSearch   = '';

  profileOpen  = false;

  ngOnInit(): void {
    this.s.init();
    this.s.isAdmin = this.auth.isAdmin();
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
    this.profileOpen = !this.profileOpen;
  }

  /** Ir a la pantalla de login: es la única vía para obtener rol admin. */
  goToLogin(): void {
    this.profileOpen = false;
    this.router.navigate(['/login']);
  }

  logout(): void {
    this.profileOpen = false;
    this.s.isAdmin   = false;
    this.auth.logout();
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(e: MouseEvent): void {
    const target = e.target as HTMLElement;
    if (!target.closest('.h-user-wrap')) this.profileOpen = false;
  }
}
