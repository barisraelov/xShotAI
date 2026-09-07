import Logo from '../components/Logo'
import './Terms.css'

export default function Terms({ navigate, prevView }) {
  const backTo = prevView && prevView !== 'terms' ? prevView : 'dashboard'

  return (
    <div className="screen-enter">
      <div className="top-bar terms-topbar">
        <button
          type="button"
          className="terms-back"
          onClick={() => navigate(backTo)}
        >
          ← Back
        </button>
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      <article className="terms-doc">
        <h1>Terms and Conditions <span>(Terms of Service)</span></h1>
        <p className="terms-updated">Last Updated: September 7, 2026</p>

        <p>
          Welcome to xShot AI (&ldquo;we,&rdquo; &ldquo;our,&rdquo; or
          &ldquo;us&rdquo;). These Terms and Conditions (&ldquo;Terms&rdquo;)
          govern your access to and use of our web application, website, and
          related services (collectively, the &ldquo;Service&rdquo;).
        </p>
        <p>
          By accessing, registering for, or using our Service, you agree to be
          bound by these Terms. If you do not agree, do not use the Service.
        </p>

        <h2>1. Eligibility &amp; User Accounts</h2>
        <ul>
          <li>
            <strong>Eligibility:</strong> You must be at least 13 years of age
            (or the legal age required in your jurisdiction) to use the Service.
          </li>
          <li>
            <strong>Account Security:</strong> When creating an account, you
            agree to provide accurate and complete information. You are solely
            responsible for maintaining the confidentiality of your credentials
            and for all activities that occur under your account.
          </li>
        </ul>

        <h2>2. User Content &amp; Media Uploads</h2>
        <ul>
          <li>
            <strong>Ownership:</strong> You retain ownership of any data, video
            files, images, or other materials you upload or submit to the
            Service (&ldquo;User Content&rdquo;).
          </li>
          <li>
            <strong>License to Operate:</strong> By uploading User Content, you
            grant us a worldwide, non-exclusive, royalty-free license to use,
            store, process, and analyze your content solely for the purpose of
            operating, maintaining, and improving the Service.
          </li>
          <li>
            <strong>Content Responsibility:</strong> You represent and warrant
            that you own or have obtained all necessary rights and permissions
            to upload your User Content, and that your content does not violate
            any third-party intellectual property, privacy, or publicity rights.
          </li>
        </ul>

        <h2>3. Intellectual Property Rights</h2>
        <p>
          All software, algorithms, designs, user interfaces, documentation,
          trademarks, and logos associated with the Service are the exclusive
          intellectual property of xShot AI Team and its licensors.
        </p>
        <p>You agree not to:</p>
        <ul>
          <li>Copy, modify, distribute, sell, or lease any part of our Service.</li>
          <li>
            Reverse engineer, decompile, or attempt to extract the source code
            or algorithms of the Service.
          </li>
          <li>
            Use automated scripts, scrapers, or bots to access or monitor the
            Service without our prior written consent.
          </li>
        </ul>

        <h2>4. Service Availability &amp; Analytics Disclaimer</h2>
        <ul>
          <li>
            <strong>Informational Purposes Only:</strong> The Service provides
            automated computational analysis, measurements, and data insights.
            All analytics, metrics, and outputs are provided for informational
            and recreational purposes only. We do not guarantee 100% accuracy,
            completeness, or reliability of any analysis or output.
          </li>
          <li>
            <strong>&ldquo;AS IS&rdquo; Basis:</strong> The Service is provided
            on an &ldquo;AS IS&rdquo; and &ldquo;AS AVAILABLE&rdquo; basis
            without warranties of any kind, either express or implied.
          </li>
          <li>
            <strong>Service Interruptions:</strong> We do not guarantee that the
            Service will always be uninterrupted, timely, secure, or error-free.
            We reserve the right to modify or discontinue any part of the
            Service at any time.
          </li>
        </ul>

        <h2>5. Limitation of Liability</h2>
        <p>
          To the maximum extent permitted by applicable law, in no event shall
          xShot AI Team, its founders, employees, or affiliates be liable for
          any indirect, incidental, special, consequential, or punitive damages,
          including loss of data, profits, or goodwill, arising out of or in
          connection with your use of or inability to use the Service.
        </p>
        <p>
          Our total aggregate liability for all claims arising out of these
          Terms or the Service shall not exceed the amount you paid to us (if
          any) to use the Service during the twelve (12) months preceding the
          claim.
        </p>

        <h2>6. Termination</h2>
        <p>
          We reserve the right to suspend or terminate your account and access
          to the Service at our sole discretion, without prior notice, if you
          violate these Terms or engage in conduct harmful to the Service or
          other users.
        </p>

        <h2>7. Governing Law and Jurisdiction</h2>
        <p>
          These Terms shall be governed by and construed in accordance with the
          laws of the State of Israel, without regard to its conflict of law
          principles. Any dispute arising under or in connection with these
          Terms shall be subject to the exclusive jurisdiction of the competent
          courts located in Tel Aviv, Israel.
        </p>

        <h2>8. Changes to These Terms</h2>
        <p>
          We may revise these Terms from time to time. If we make material
          changes, we will notify you by updating the &ldquo;Last Updated&rdquo;
          date at the top of this page or via in-app notice. Your continued use
          of the Service after any modifications constitutes acceptance of the
          new Terms.
        </p>

        <h2>9. Contact Us</h2>
        <p>
          If you have any questions or concerns regarding these Terms, please
          contact us at:
        </p>
        <p className="terms-contact">
          Email:{' '}
          <a href="mailto:xshotaiapp@gmail.com">xshotaiapp@gmail.com</a>
        </p>
      </article>

      <button
        type="button"
        className="terms-back terms-back--foot"
        onClick={() => navigate(backTo)}
      >
        ← Back
      </button>
    </div>
  )
}
