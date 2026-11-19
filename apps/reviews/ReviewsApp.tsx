// Reviews' root component, as oneberth's shell loads it. One panel, a placeholder for now.
import "./reviews.css";

export default function ReviewsApp() {
  return (
    <main className="reviews-area">
      <section className="reviews-panel" aria-label="Reviews">
        <p>something to review</p>
      </section>
    </main>
  );
}
