// Terms & Conditions, public at /terms.
//
// WRITTEN FROM THE PRODUCT AS BUILT. Every clause describes something the
// application actually does, or declines something it does not. In particular
// it does NOT claim that AcademicAI:
//   * verifies identity, student ID cards or university records
//   * is affiliated with, or speaks for, any university
//   * guarantees that a date, deadline, venue or reminder is correct or arrives
//   * has a privacy policy, certification, uptime commitment or integration
//     that does not exist
// Where the honest position is uncertain, the wording is cautious ("may",
// "we try to") rather than a promise.
//
// A document, not a set of cards: one reading column at a measure, numbered
// sections (the numbers are real references - "see section 6"), and a
// contents list that is sticky beside the text on a laptop and folds away on
// a phone.

import PublicNav from '../components/PublicNav.jsx';
import PublicFooter from '../components/PublicFooter.jsx';
import { TERMS_EFFECTIVE } from '../lib/terms.js';
const CONTACT_EMAIL = 'helloacademicai@gmail.com';
const Mail = () => <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;

const SECTIONS = [
  {
    id: 'introduction', title: 'Introduction and acceptance',
    body: (
      <>
        <p>
          These Terms &amp; Conditions (the “Terms”) govern your use of AcademicAI,
          including the website and the application you sign in to. By creating an
          account or using AcademicAI, you agree to these Terms. If you do not agree,
          do not use AcademicAI.
        </p>
        <p>
          “We”, “us” and “our” mean the people who build and run AcademicAI. “You”
          means the person using it.
        </p>
      </>
    ),
  },
  {
    id: 'what-it-is', title: 'What AcademicAI is',
    body: (
      <>
        <p>
          AcademicAI helps university students keep track of academic information
          — assignments, tests, deadlines, venue changes, timetables and
          announcements — shared within an academic community. A community is
          defined by a university, a department, a level and an academic session.
        </p>
        <p>
          AcademicAI is an independent, early-stage student project. It is{' '}
          <strong>not</strong> affiliated with, endorsed by or operated on behalf of
          any university, and it is not connected to any university system. Nothing
          in AcademicAI is an official communication from your university.
        </p>
      </>
    ),
  },
  {
    id: 'eligibility', title: 'Eligibility and account creation',
    body: (
      <>
        <p>
          To create an account you need an email address on a domain your university
          has approved for students. Where email verification is switched on, you must
          confirm that address with the code we send before you can join a community.
        </p>
        <p>
          Verifying your email shows only that you control that address. AcademicAI
          does <strong>not</strong> verify your identity, check student ID cards or
          confirm anything against your university’s records. The matric number you
          enter at registration is stored as you typed it and is not checked.
        </p>
        <p>
          You may hold one active community membership at a time. Joining an active
          community requires approval from one of its course representatives.
        </p>
      </>
    ),
  },
  {
    id: 'your-account', title: 'Your account',
    body: (
      <>
        <p>You are responsible for your account. In particular, you agree to:</p>
        <ul>
          <li>give accurate information when you register, including your name, department, level and session;</li>
          <li>keep your password private and not share your account with anyone else;</li>
          <li>use only your own university email address;</li>
          <li>tell us at <Mail /> if you believe someone else has accessed your account.</li>
        </ul>
        <p>
          Changing the email address on your account signs you out everywhere and
          requires the new address to be verified again.
        </p>
      </>
    ),
  },
  {
    id: 'records', title: 'Academic records and information you submit',
    body: (
      <>
        <p>
          Official information in a community — events, deadlines, timetables,
          announcements and their attached files — is published by that community’s
          course representatives. AcademicAI keeps it organised and shows its history
          of changes, but it does not check that information against any university
          source.
        </p>
        <p>
          Records are only as accurate as what was published.{' '}
          <strong>Always confirm important dates, deadlines and venues with your
          lecturers or your university’s official channels.</strong> We are not
          responsible for decisions you make based on information shown in
          AcademicAI.
        </p>
        <p>
          When you submit anything — a message to be read into a record, a chat
          question, a reminder, a file — you confirm that you are allowed to share it
          and that it does not break the law or anyone else’s rights.
        </p>
      </>
    ),
  },
  {
    id: 'ai', title: 'AI suggestions and interpretation',
    body: (
      <>
        <p>
          Some features use automated interpretation, including artificial
          intelligence, to read a pasted announcement into a draft record, to answer
          questions about your community’s records, and to suggest reminders.
        </p>
        <ul>
          <li>
            <strong>AI proposes; people decide.</strong> A draft record created from a
            message is not published until a course representative reviews it.
            AcademicAI’s AI never publishes official information on its own.
          </li>
          <li>
            AI output can be incomplete or wrong. Treat answers and suggestions as help,
            not as authority, and check anything important.
          </li>
          <li>
            Depending on how AcademicAI is configured, text you submit to these features
            may be processed by a third-party AI service provider in order to produce a
            result.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: 'reminders', title: 'Reminders and notifications',
    body: (
      <>
        <p>
          AcademicAI can remind you about academic events and about personal
          reminders you set. Reminder times are read on your university’s clock. When
          a reminder is due, it appears in the app’s notifications and is also sent by
          email.
        </p>
        <p>
          Email delivery depends on third-party email services and your own mailbox,
          and the app’s notifications depend on the service running. We try to deliver
          every reminder on time, but we <strong>cannot guarantee</strong> that any
          notification or email arrives, or arrives when expected. Do not rely on
          AcademicAI as your only reminder of anything important.
        </p>
        <p>
          Personal reminders are private to you. They are not official records, and
          other members, including course representatives, cannot see them.
        </p>
      </>
    ),
  },
  {
    id: 'community', title: 'Communities and member information',
    body: (
      <>
        <p>
          When you are a member of a community, the other members of that community
          can see your name and whether you are a course representative. Your email
          address is not shown to other members.
        </p>
        <p>
          Course representatives can see membership requests for their community so
          that they can approve or reject them. Community members can see the records
          and announcements published in their community, and the history of changes
          made to them.
        </p>
      </>
    ),
  },
  {
    id: 'reps', title: 'Course representatives and community roles',
    body: (
      <>
        <p>
          Course representatives are chosen by the members of their community through
          the elections in AcademicAI, and can be removed the same way. Being a course
          representative in AcademicAI does not mean your university has appointed you
          to any role.
        </p>
        <p>If you are a course representative, you agree to:</p>
        <ul>
          <li>publish only information you believe to be accurate, and correct it promptly when it changes;</li>
          <li>review AI-drafted records carefully before publishing them;</li>
          <li>approve or reject membership requests fairly, for students who belong to the community;</li>
          <li>not use the role to mislead, pressure or exclude other members.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'acceptable-use', title: 'Acceptable use',
    body: (
      <>
        <p>You agree not to:</p>
        <ul>
          <li>post false or misleading academic information on purpose;</li>
          <li>impersonate another person, or misrepresent your role or your university;</li>
          <li>harass, threaten or abuse other members;</li>
          <li>upload unlawful content, malware, or material you do not have the right to share;</li>
          <li>send spam or use AcademicAI to advertise;</li>
          <li>try to access accounts, communities or information that are not yours;</li>
          <li>interfere with elections, or try to get around membership or voting rules;</li>
          <li>disrupt, overload, scrape or reverse-engineer the service.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'responsibilities', title: 'Your responsibilities',
    body: (
      <p>
        You remain responsible for your own academic work and for meeting your
        university’s requirements and deadlines. AcademicAI is a tool to help you keep
        track of information; it does not replace your university’s official channels,
        your lecturers, or your own judgement.
      </p>
    ),
  },
  {
    id: 'ip', title: 'Intellectual property',
    body: (
      <>
        <p>
          You keep ownership of what you submit. By submitting it, you allow us to
          store, display and process it as needed to run AcademicAI — for example, to
          show a published record to the members of its community, or to turn a
          message into a draft record.
        </p>
        <p>
          The AcademicAI name, design and software belong to the people who build it.
          You may not copy or reuse them except as these Terms allow or the law
          permits.
        </p>
      </>
    ),
  },
  {
    id: 'availability', title: 'Service availability and changes',
    body: (
      <p>
        AcademicAI is under active development. Features may change, be added or be
        removed, and the service may sometimes be unavailable, slow or interrupted —
        including for maintenance. We do not promise any particular level of
        availability, and we may stop offering AcademicAI, in whole or in part.
      </p>
    ),
  },
  {
    id: 'termination', title: 'Suspension and termination',
    body: (
      <>
        <p>
          We may suspend or close an account that breaks these Terms, puts other members
          at risk, or harms the service. Where it is reasonable, we will try to tell you
          why.
        </p>
        <p>
          You can stop using AcademicAI at any time and can leave your community from
          the Community section. If you would like to ask about removing your account,
          contact us at <Mail />.
        </p>
      </>
    ),
  },
  {
    id: 'liability', title: 'Limitation of liability',
    body: (
      <>
        <p>
          AcademicAI is provided “as is” and “as available”, without warranties of any
          kind, to the extent the law allows.
        </p>
        <p>
          To the extent the law allows, we are not liable for any loss or harm arising
          from your use of AcademicAI, including missed deadlines, missed or late
          reminders, inaccurate records or AI output, or information published by
          course representatives or other members. Nothing in these Terms limits any
          right you have that cannot be limited by law.
        </p>
      </>
    ),
  },
  {
    id: 'changes', title: 'Changes to these Terms',
    body: (
      <p>
        We may update these Terms as AcademicAI changes. When we do, we will change the
        effective date at the top of this page. By continuing to use AcademicAI after
        an update, you accept the updated Terms.
      </p>
    ),
  },
  {
    id: 'contact', title: 'Contact',
    body: (
      <p>
        Questions about these Terms, or about AcademicAI, can be sent to <Mail />.
      </p>
    ),
  },
];

function TocList() {
  return (
    <ol className="terms__toclist">
      {SECTIONS.map((section, i) => (
        <li key={section.id}>
          <a href={`#${section.id}`}>
            <span className="terms__tocn" aria-hidden="true">{i + 1}</span>
            {section.title}
          </a>
        </li>
      ))}
    </ol>
  );
}

export default function TermsPage() {
  return (
    <div className="public">
      <PublicNav />
      <main className="public__main terms" id="main">
        <div className="wrap">
          <header className="terms__head">
            <h1 className="terms__title">Terms &amp; Conditions</h1>
            <p className="terms__date">Effective {TERMS_EFFECTIVE}</p>
            <p className="terms__lede">
              The terms for using AcademicAI, written for what it actually does: what it
              is, what it is not, and what you and we are each responsible for.
            </p>
          </header>

          <div className="terms__layout">
            {/* A laptop keeps the contents open beside the text; a phone folds
                them into one line above it, so they cost no height until
                opened. Two renderings of one list, only one ever displayed:
                a single <details> cannot be open on one and shut on the other. */}
            <nav className="terms__toc" aria-label="Contents">
              <p className="terms__toclabel">Contents</p>
              <TocList />
            </nav>
            <details className="terms__tocfold">
              <summary>Contents <span className="t-meta">· {SECTIONS.length} sections</span></summary>
              <nav aria-label="Contents"><TocList /></nav>
            </details>

            <article className="terms__doc">
              {SECTIONS.map((section, i) => (
                <section key={section.id} id={section.id} className="terms__sec"
                         aria-labelledby={`${section.id}-h`}>
                  <h2 id={`${section.id}-h`}>
                    <span className="terms__n">{i + 1}.</span> {section.title}
                  </h2>
                  {section.body}
                </section>
              ))}
            </article>
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}
