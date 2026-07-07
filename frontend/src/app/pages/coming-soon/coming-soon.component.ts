import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-coming-soon',
  standalone: true,
  imports: [],
  template: `
    <div class="coming-soon-wrap">
      <div class="cs-card">
        <div class="cs-glow"></div>
        <div class="cs-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
               stroke="#00E58F" stroke-width="1.4" stroke-linecap="round">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
        </div>
        <h2 class="cs-title">Próximamente</h2>
        <p class="cs-sub">Esta funcionalidad está en desarrollo y estará disponible próximamente.</p>
        <div class="cs-tags">
          <span class="cs-tag">En construcción</span>
          <span class="cs-tag green">PriceHunter Pro</span>
        </div>
        <button class="cs-back" (click)="goHome()">← Volver al Dashboard</button>
      </div>
    </div>
  `,
})
export class ComingSoonComponent {
  private router = inject(Router);
  goHome(): void { this.router.navigate(['/oportunidades']); }
}
